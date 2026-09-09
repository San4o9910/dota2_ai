import hashlib
import hmac
import json
import math
import os
import re
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .config import PART_BYTES, MAX_VIDEO_BYTES, job_directory, media_root, service_token
from .db import database
from . import budget
from .build_meta import cache as build_cache, router as build_meta_router
from .workshop_builds import cache as workshop_cache


@asynccontextmanager
async def lifespan(app):
    build_cache.start()
    workshop_cache.start()
    try:
        yield
    finally:
        build_cache.stop()
        workshop_cache.stop()

app = FastAPI(title="NARMA match analysis", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(build_meta_router)

@app.middleware("http")
async def access_log(request: Request, call_next):
    request_id = str(uuid4())
    started = time.monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        route = request.scope.get("route")
        # Route templates only: never a raw URL, query, header or request body.
        print(json.dumps({"event":"http_request", "request_id":request_id,
            "method":request.method if request.method in {"GET","POST","PUT","DELETE","HEAD","OPTIONS","PATCH"} else "OTHER",
            "route":getattr(route, "path", "unmatched"), "status":status,
            "duration_ms":round((time.monotonic()-started)*1000)}), flush=True)

@app.get("/livez")
def live():
    return {"status":"alive"}

@app.get("/readyz")
def ready():
    try:
        service_token()
        with database() as connection:
            connection.execute("SELECT 1 FROM video_jobs LIMIT 1")
            connection.execute("SELECT 1 FROM replay_jobs LIMIT 1")
            connection.execute("SELECT 1 FROM hero_pool_match_notes LIMIT 1")
            migrated = connection.execute("""SELECT count(*) AS n FROM video_schema_migrations
                WHERE name IN ('010_hero_pool_progress.sql','008_replay_coaching_history.sql','009_hermes_reviews.sql','011_hermes_runtime.sql','012_learning_curriculum.sql','013_chatgpt_auth.sql','014_chatgpt_calls.sql','015_hermes_chatgpt_provider.sql')""").fetchone()
            if migrated["n"] != 8:
                raise RuntimeError("Progress schema not ready")
        with tempfile.TemporaryFile(dir=media_root()) as handle:
            handle.write(b"ready"); handle.flush()
        return {"status":"ready", "checks":["config","postgresql","schema","media"]}
    except Exception:
        return JSONResponse({"status":"not_ready"}, status_code=503)

def principal(authorization: Annotated[str | None, Header()] = None, x_narma_owner: Annotated[str | None, Header()] = None):
    # This is a private application-to-service boundary. Only the authenticated
    # website can supply an owner; neither credential nor header reaches its UI.
    if not hmac.compare_digest(authorization or "", "Bearer " + service_token()):
        raise HTTPException(401, "Нет доступа.")
    if not x_narma_owner or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", x_narma_owner):
        raise HTTPException(400, "Нет аккаунта.")
    return x_narma_owner

Owner = Annotated[str, Depends(principal)]

class CreateVideo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    filename: str = Field(min_length=5, max_length=180)
    size_bytes: int = Field(ge=16, le=MAX_VIDEO_BYTES)
    account_id: int = Field(ge=1, le=4294967294)
    nickname: str = Field(min_length=1, max_length=128)

def owned(connection, owner, job_id, lock=False):
    row = connection.execute("SELECT * FROM video_jobs WHERE id=%s AND owner_id=%s AND state<>'deleted'" + (" FOR UPDATE" if lock else ""), (job_id, owner)).fetchone()
    if row is None:
        raise HTTPException(404, "Видео не найдено.")
    return row

def public(row):
    return {**{key: row[key] for key in ("id", "filename", "size_bytes", "state", "nickname", "frame_count", "processed_frames", "duration_seconds", "failure_code", "created_at")},"identity_status":"nickname_only"}

@app.get("/v1/videos")
def videos(owner: Owner):
    with database() as connection:
        rows = connection.execute("SELECT * FROM video_jobs WHERE owner_id=%s AND state<>'deleted' ORDER BY created_at DESC LIMIT 30", (owner,)).fetchall()
        worker = connection.execute("SELECT 1 FROM video_workers WHERE last_seen>now()-interval '5 minutes' LIMIT 1").fetchone()
    allowance=budget.status()
    return {"videos": [public(row) for row in rows], "worker_ready": bool(worker), "max_bytes": MAX_VIDEO_BYTES,
        "frame_budget":int(os.environ.get('VIDEO_FRAME_BUDGET','3600')),
        "budget_available":allowance['enabled'] and allowance['available_microusd']>=budget.RESERVATION}

@app.post("/v1/videos", status_code=201)
def create_video(body: CreateVideo, owner: Owner):
    if not re.fullmatch(r"[^\x00-\x1f\x7f/\\]+\.(?:mp4|mkv|webm|mov)", body.filename, re.I):
        raise HTTPException(400, "Выберите MP4, MKV, WebM или MOV.")
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (owner,))
        existing = connection.execute("SELECT * FROM video_jobs WHERE id=%s", (body.id,)).fetchone()
        if existing:
            if existing["owner_id"] != owner or existing["filename"] != body.filename or existing["size_bytes"] != body.size_bytes or existing["account_id"] != body.account_id:
                raise HTTPException(409, "Этот запрос уже относится к другому файлу.")
            if existing["state"] == "deleted":
                raise HTTPException(409, "Видео удалено. Начните новую загрузку.")
            return {"video": public(existing), "part_bytes": PART_BYTES}
        allowance=budget.status(connection)
        if not allowance['enabled'] or allowance['available_microusd']<budget.RESERVATION:
            raise HTTPException(503, "Тестовый бюджет видеоанализа исчерпан или приостановлен. Сохранённые результаты доступны.")
        limits = connection.execute("SELECT count(*) FILTER (WHERE created_at>now()-interval '1 day') AS daily, coalesce(sum(size_bytes) FILTER(WHERE storage_deleted_at IS NULL),0) AS stored FROM video_jobs WHERE owner_id=%s", (owner,)).fetchone()
        if limits["daily"] >= 4 or limits["stored"] + body.size_bytes > 8 * 1024**3:
            raise HTTPException(429, "Лимит видео исчерпан. Удалите ненужные файлы или повторите позже.")
        row = connection.execute("INSERT INTO video_jobs(id,owner_id,account_id,nickname,filename,size_bytes) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *", (body.id,owner,body.account_id,body.nickname,body.filename,body.size_bytes)).fetchone()
        directory = job_directory(body.id)
        if directory.exists():
            # A rolled-back initialization may leave an empty directory only.
            if any(directory.iterdir()):
                raise HTTPException(409, "Повторите загрузку с новым заданием.")
        else:
            directory.mkdir(mode=0o700, parents=True)
    return {"video": public(row), "part_bytes": PART_BYTES}

@app.get("/v1/videos/{job_id}")
def get_video(job_id: UUID, owner: Owner, after: int = -1):
    with database() as connection:
        row = owned(connection, owner, job_id)
        parts = connection.execute("SELECT part_number FROM video_parts WHERE job_id=%s ORDER BY part_number", (job_id,)).fetchall()
        batches = connection.execute("SELECT first_frame,last_frame,first_pts_seconds,last_pts_seconds,payload FROM video_batches WHERE job_id=%s AND first_frame>%s ORDER BY first_frame LIMIT 30", (job_id, max(-1,after))).fetchall()
    return {"video": public(row), "parts": [p["part_number"] for p in parts], "batches": batches,
            "next_cursor": batches[-1]["first_frame"] if len(batches)==30 else None}

@app.put("/v1/videos/{job_id}/parts/{part_number}")
async def upload_part(job_id: UUID, part_number: int, request: Request, owner: Owner):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > PART_BYTES:
            raise HTTPException(413, "Часть файла слишком велика.")
        data.extend(chunk)
    with database() as connection:
        row = owned(connection, owner, job_id, True)
        expected = min(PART_BYTES, row["size_bytes"] - (part_number-1)*PART_BYTES)
        if row["state"] != "uploading" or part_number < 1 or part_number > math.ceil(row["size_bytes"]/PART_BYTES):
            raise HTTPException(409, "Загрузка закрыта или номер части неверен.")
        if len(data) != expected:
            raise HTTPException(400, "Часть файла передана не полностью.")
        if part_number == 1 and not (data[4:8] == b"ftyp" or data[:4] == b"\x1aE\xdf\xa3"):
            raise HTTPException(415, "Не удалось определить формат видео.")
        directory = job_directory(job_id)
        temporary = directory / f"{uuid4()}.tmp"
        try:
            temporary.write_bytes(data)
            os.replace(temporary, directory / f"part-{part_number}")
            connection.execute("INSERT INTO video_parts(job_id,part_number,size_bytes,sha256) VALUES (%s,%s,%s,%s) ON CONFLICT(job_id,part_number) DO UPDATE SET size_bytes=excluded.size_bytes,sha256=excluded.sha256", (job_id,part_number,len(data),hashlib.sha256(data).hexdigest()))
        finally:
            temporary.unlink(missing_ok=True)
    return {"uploaded": True, "part_number": part_number}

@app.post("/v1/videos/{job_id}/complete")
def complete_video(job_id: UUID, owner: Owner):
    with database() as connection:
        row = owned(connection, owner, job_id, True)
        if row["state"] in ("queued", "processing", "ready"):
            return {"video": public(row)}
        if row["state"] != "uploading":
            raise HTTPException(409, "Загрузите видео заново.")
        parts = connection.execute("SELECT * FROM video_parts WHERE job_id=%s ORDER BY part_number", (job_id,)).fetchall()
        if len(parts) != math.ceil(row["size_bytes"]/PART_BYTES) or sum(p["size_bytes"] for p in parts) != row["size_bytes"]:
            raise HTTPException(409, "Переданы не все части видео.")
        directory = job_directory(job_id); digest = hashlib.sha256()
        temporary = directory / "source.pending"
        try:
            with temporary.open("wb") as destination:
                for number, part in enumerate(parts,1):
                    data = (directory / f"part-{number}").read_bytes()
                    if part["part_number"] != number or hashlib.sha256(data).hexdigest() != part["sha256"]:
                        raise HTTPException(409, "Проверка целостности видео не прошла.")
                    destination.write(data); digest.update(data)
            os.replace(temporary, directory / "source")
            row = connection.execute("UPDATE video_jobs SET state='queued',source_sha256=%s,updated_at=now() WHERE id=%s RETURNING *", (digest.hexdigest(),job_id)).fetchone()
        finally:
            temporary.unlink(missing_ok=True)
    for part in parts:
        (directory / f"part-{part['part_number']}").unlink(missing_ok=True)
    return {"video": public(row)}

@app.get("/v1/videos/{job_id}/source")
def source(job_id: UUID, owner: Owner):
    with database() as connection:
        row = owned(connection, owner, job_id)
    if row["state"] == "uploading":
        raise HTTPException(409, "Видео ещё загружается.")
    path = job_directory(job_id) / "source"
    if not path.is_file():
        raise HTTPException(404, "Файл не найден.")
    mime = "video/webm" if row["filename"].lower().endswith(".webm") else "video/mp4" if row["filename"].lower().endswith((".mp4", ".mov")) else "video/x-matroska"
    return FileResponse(path, media_type=mime, headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})

@app.delete("/v1/videos/{job_id}")
def delete_video(job_id: UUID, owner: Owner):
    with database() as connection:
        row=connection.execute("SELECT id FROM video_jobs WHERE id=%s AND owner_id=%s FOR UPDATE",(job_id,owner)).fetchone()
        if not row:
            raise HTTPException(404,"Видео не найдено.")
        connection.execute("UPDATE video_jobs SET state='deleted',lease_token=NULL,lease_expires_at=NULL,updated_at=now() WHERE id=%s", (job_id,))
        connection.execute("DELETE FROM video_batches WHERE job_id=%s", (job_id,))
        connection.execute("DELETE FROM video_parts WHERE job_id=%s", (job_id,))
    try:
        if job_directory(job_id).exists():
            shutil.rmtree(job_directory(job_id))
    except OSError:
        raise HTTPException(503,"Доступ к видео закрыт. Удаление файла будет повторено сервером.")
    with database() as connection:
        connection.execute("UPDATE video_jobs SET storage_deleted_at=now() WHERE id=%s AND state='deleted'",(job_id,))
    return {"deleted": True}

# Browser entrypoint has its own cookie/session boundary and never accepts the
# service's owner header as an end-user identity.
from .web import attach_web
attach_web(app)
from .replay_jobs import attach_replays
attach_replays(app)
from .replay_archive import attach_replay_archive
attach_replay_archive(app)
from .hero_pool import attach_hero_pool
attach_hero_pool(app)
from .learning import attach_learning
attach_learning(app)
from .hermes_bridge import attach_hermes
attach_hermes(app)
from .chatgpt_auth import attach_chatgpt
attach_chatgpt(app)
from .explore import router as explore_router
app.include_router(explore_router)

from pathlib import Path
from fastapi.staticfiles import StaticFiles
STATIC_ROOT=Path(__file__).parent/'static'
app.mount('/assets',StaticFiles(directory=STATIC_ROOT),name='portal-assets')

@app.get('/')
@app.get('/heroes')
@app.get('/builds')
@app.get('/learn')
@app.get('/practice')
@app.get('/updates')
def explore_page():
    return FileResponse(STATIC_ROOT/'explore.html',media_type='text/html',headers={'Cache-Control':'no-cache'})


@app.get('/setup')
@app.get('/videos')
@app.get('/replays')
@app.get('/hero-pool')
@app.get('/player')
@app.get('/my-learning')
@app.get('/account')
def portal_page():
    return FileResponse(STATIC_ROOT/'index.html',media_type='text/html',headers={'Cache-Control':'no-store'})

@app.middleware('http')
async def portal_headers(request: Request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://cdn.cloudflare.steamstatic.com https://clan.fastly.steamstatic.com; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    response.headers['Strict-Transport-Security']='max-age=31536000'
    if request.url.path.startswith('/assets/'):
        response.headers['Cache-Control']='no-cache'
    return response
