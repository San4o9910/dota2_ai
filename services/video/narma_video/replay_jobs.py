"""Cookie-authorized, chunked .dem uploads and a durable local-parser queue.

The footer identifies the selected account only. A queued upload is never an
analysis result: a worker must parse gameplay, verify identity and call
finish_replay with a complete evidence report. This module makes no paid calls.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .config import PART_BYTES, media_root
from .db import database
from .replay_metadata import parse_demo_metadata, resolve_player
from .web import account_required, csrf, json_body, reject

MAX_REPLAY_BYTES = 512 * 1024**2
OWNER_STORAGE_BYTES = 2 * 1024**3
GLOBAL_STORAGE_BYTES = 4 * 1024**3
DAILY_JOBS = 8
QUOTA_LOCK = 643847219
LEASE_SECONDS = 300
MAX_RESULT_BYTES = 8 * 1024**2


class CreateReplay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    filename: str = Field(min_length=5, max_length=180)
    size_bytes: int = Field(ge=20, le=MAX_REPLAY_BYTES)
    nickname: str | None = Field(default=None, min_length=1, max_length=128)
    match_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{7,11}$")


def replay_directory(job_id) -> Path:
    return media_root() / "replays" / str(UUID(str(job_id)))


def owned(connection, owner_id, job_id, lock=False):
    row = connection.execute("""SELECT * FROM replay_jobs
        WHERE id=%s AND owner_id=%s AND state<>'deleted'""" + (" FOR UPDATE" if lock else ""),
        (job_id, owner_id)).fetchone()
    if row is None:
        reject(404, "REPLAY_NOT_FOUND", "Разбор не найден.")
    return row


def public(row):
    return {**{key: row[key] for key in (
        "id", "filename", "size_bytes", "nickname", "match_id", "state",
        "progress", "failure_code", "created_at", "updated_at")},
        "source_retained": row["storage_deleted_at"] is None}


def list_replays(owner_id):
    with database() as connection:
        rows = connection.execute("""SELECT * FROM replay_jobs WHERE owner_id=%s
            AND state<>'deleted' ORDER BY created_at DESC LIMIT 30""", (owner_id,)).fetchall()
        worker = connection.execute("SELECT 1 FROM replay_workers WHERE last_seen>now()-interval '5 minutes' LIMIT 1").fetchone()
    return {"replays": [public(row) for row in rows], "worker_ready": bool(worker),
            "max_bytes": MAX_REPLAY_BYTES, "part_bytes": PART_BYTES}


def create_replay(body: CreateReplay, owner_id):
    if not re.fullmatch(r"[^\x00-\x1f\x7f/\\]+\.dem", body.filename, re.I):
        reject(400, "REPLAY_FILE_TYPE", "Выберите реплей Dota 2 в формате .dem.")
    with database() as connection:
        # One lock covers the global disk reservation and concurrent creation.
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (QUOTA_LOCK,))
        profile = connection.execute("SELECT account_id,nickname FROM portal_dota_profiles WHERE owner_id=%s", (owner_id,)).fetchone()
        nickname = (body.nickname or (profile["nickname"] if profile else "")).strip()
        if not nickname or re.search(r"[\x00-\x1f\x7f]", nickname):
            reject(400, "DOTA_NICKNAME", "Укажите свой ник из этого реплея.")
        previous = connection.execute("SELECT * FROM replay_jobs WHERE id=%s", (body.id,)).fetchone()
        if previous:
            if (previous["owner_id"] != owner_id or previous["filename"] != body.filename
                    or previous["size_bytes"] != body.size_bytes
                    or previous["requested_nickname"] != nickname
                    or previous["expected_match_id"] != body.match_id or previous["state"] == "deleted"):
                reject(409, "REPLAY_REQUEST_REUSED", "Этот запрос уже относится к другой загрузке. Выберите файл заново.")
            return {"replay": public(previous), "part_bytes": PART_BYTES}
        own = connection.execute("""SELECT count(*) FILTER (WHERE created_at>now()-interval '1 day') AS daily,
            count(*) FILTER (WHERE state IN ('uploading','queued','processing')) AS active,
            coalesce(sum(size_bytes) FILTER (WHERE storage_deleted_at IS NULL),0) AS stored
            FROM replay_jobs WHERE owner_id=%s""", (owner_id,)).fetchone()
        total = connection.execute("SELECT coalesce(sum(size_bytes),0) AS stored FROM replay_jobs WHERE storage_deleted_at IS NULL").fetchone()["stored"]
        if own["daily"] >= DAILY_JOBS or own["active"] >= 2:
            reject(429, "REPLAY_QUOTA", "Дождитесь завершения текущих разборов. Доступно до восьми загрузок за сутки.")
        if own["stored"] + body.size_bytes > OWNER_STORAGE_BYTES or total + body.size_bytes > GLOBAL_STORAGE_BYTES:
            reject(429, "REPLAY_STORAGE_QUOTA", "Удалите ненужные реплеи, чтобы освободить место.")
        root = media_root() / "replays"
        root.mkdir(mode=0o700, exist_ok=True)
        # Joining parts briefly needs one additional source-sized allocation.
        pending = connection.execute("SELECT coalesce(sum(size_bytes),0) AS n FROM replay_jobs WHERE state='uploading'").fetchone()["n"]
        if shutil.disk_usage(root).free < 2 * (pending + body.size_bytes) + 1024**3:
            reject(507, "REPLAY_STORAGE", "На сервере недостаточно места для реплея.")
        directory = replay_directory(body.id)
        if directory.exists() and any(directory.iterdir()):
            reject(409, "REPLAY_REQUEST_REUSED", "Повторите загрузку с новым заданием.")
        directory.mkdir(mode=0o700, exist_ok=True)
        row = connection.execute("""INSERT INTO replay_jobs
            (id,owner_id,filename,size_bytes,requested_nickname,nickname,expected_match_id,account_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (body.id, owner_id, body.filename, body.size_bytes, nickname, nickname,
             body.match_id, profile["account_id"] if profile else None)).fetchone()
    return {"replay": public(row), "part_bytes": PART_BYTES}


def get_replay(job_id, owner_id):
    with database() as connection:
        row = owned(connection, owner_id, job_id)
        parts = connection.execute("SELECT part_number FROM replay_parts WHERE job_id=%s ORDER BY part_number", (job_id,)).fetchall()
        archive = previous_report(connection, row)
    current = row["state"] == "ready"
    return {"replay": public(row), "parts": [part["part_number"] for part in parts],
            "report": row["result_payload"] if current else (archive["report"] if archive else None),
            "report_is_previous": bool(not current and archive), "archived_report": archive}


def previous_report(connection, row):
    """Read snapshots only after ownership/lease resolution, with exact identity.

    Prefer the latest report containing ready coaching. Its own evidence remains
    available even when it cannot safely be carried into a refreshed report.
    """
    return connection.execute("""SELECT id,created_at,report FROM replay_report_history
        WHERE job_id=%s AND source_sha256=%s AND match_id=%s AND account_id=%s
        ORDER BY (report->'coaching'->>'status'='ready') DESC NULLS LAST,id DESC LIMIT 1""",
        (row["id"], row["source_sha256"], row["match_id"], row["account_id"])).fetchone()


def store_part(job_id, part_number, data: bytes, owner_id):
    with database() as connection:
        row = owned(connection, owner_id, job_id, True)
        if row["state"] != "uploading" or not 1 <= part_number <= math.ceil(row["size_bytes"] / PART_BYTES):
            reject(409, "REPLAY_UPLOAD_CLOSED", "Загрузка закрыта или номер части неверен.")
        expected = min(PART_BYTES, row["size_bytes"] - (part_number - 1) * PART_BYTES)
        if len(data) != expected:
            reject(400, "REPLAY_PART_INCOMPLETE", "Часть реплея передана не полностью.")
        if part_number == 1 and data[:8] != b"PBDEMS2\x00":
            reject(415, "REPLAY_FILE_TYPE", "Это не реплей Dota 2 Source 2. Выберите исходный .dem.")
        digest = hashlib.sha256(data).hexdigest()
        previous = connection.execute("SELECT sha256,size_bytes FROM replay_parts WHERE job_id=%s AND part_number=%s", (job_id, part_number)).fetchone()
        if previous and (previous["sha256"] != digest or previous["size_bytes"] != len(data)):
            reject(409, "REPLAY_PART_CHANGED", "Содержимое загруженной части изменилось. Начните новую загрузку.")
        directory = replay_directory(job_id)
        temporary = directory / (uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as handle:
                os.chmod(temporary, 0o600)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, directory / f"part-{part_number}")
            connection.execute("""INSERT INTO replay_parts(job_id,part_number,size_bytes,sha256)
                VALUES (%s,%s,%s,%s) ON CONFLICT(job_id,part_number) DO NOTHING""",
                (job_id, part_number, len(data), digest))
            connection.execute("UPDATE replay_jobs SET updated_at=now() WHERE id=%s", (job_id,))
        finally:
            temporary.unlink(missing_ok=True)
    return {"uploaded": True, "part_number": part_number}


def _resolve_identity(connection, row, metadata, digest):
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (row["owner_id"],))
    profile = connection.execute("SELECT account_id FROM portal_dota_profiles WHERE owner_id=%s FOR UPDATE", (row["owner_id"],)).fetchone()
    locked = profile["account_id"] if profile else row["account_id"]
    if locked:
        # A Steam account can change its nickname between matches. Its stable
        # identity remains authoritative once the first upload binds it.
        candidates = [p for p in metadata["players"] if p["account_id"] == locked]
        if len(candidates) != 1:
            reject(409, "DOTA_PROFILE_LOCKED", "В этом реплее нет закреплённого за аккаунтом игрока.")
        player = candidates[0]
        if row["account_id"] is not None and row["account_id"] != locked:
            reject(409, "DOTA_PROFILE_LOCKED", "К аккаунту уже закреплён другой игрок.")
    else:
        try:
            player = resolve_player(metadata, row["requested_nickname"])
        except ValueError as error:
            code = getattr(error, "code", "DOTA_PLAYER_NOT_FOUND")
            messages = {
                "DOTA_PLAYER_AMBIGUOUS": "В реплее несколько игроков с этим ником.",
                "DOTA_IDENTITY_UNAVAILABLE": "В реплее нет Steam ID выбранного игрока.",
                "DOTA_NICKNAME_INVALID": "Укажите ник из этого матча.",
            }
            reject(400, code, messages.get(code, "В реплее нет игрока с таким ником."))
    if row["expected_match_id"] and metadata["match_id"] != row["expected_match_id"]:
        reject(409, "REPLAY_MATCH_MISMATCH", "Выбранный .dem относится к другому Match ID.")
    connection.execute("""INSERT INTO portal_dota_profiles
        (owner_id,account_id,nickname,match_id,hero_name,side,source_sha256)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(owner_id) DO UPDATE SET nickname=excluded.nickname,
            match_id=excluded.match_id,hero_name=excluded.hero_name,side=excluded.side,
            source_sha256=excluded.source_sha256,updated_at=now()""",
        (row["owner_id"], player["account_id"], player["nickname"], metadata["match_id"],
         player["hero_name"], player["side"], digest))
    return player


def complete_replay(job_id, owner_id):
    with database() as connection:
        row = owned(connection, owner_id, job_id, True)
        if row["state"] in ("queued", "processing", "ready"):
            return {"replay": public(row)}
        if row["state"] != "uploading":
            reject(409, "REPLAY_UPLOAD_CLOSED", "Загрузите реплей заново.")
        parts = connection.execute("SELECT * FROM replay_parts WHERE job_id=%s ORDER BY part_number", (job_id,)).fetchall()
        if len(parts) != math.ceil(row["size_bytes"] / PART_BYTES) or sum(p["size_bytes"] for p in parts) != row["size_bytes"]:
            reject(409, "REPLAY_UPLOAD_INCOMPLETE", "Переданы не все части реплея.")
        directory = replay_directory(job_id)
        temporary = directory / "source.pending"
        digest = hashlib.sha256()
        try:
            if shutil.disk_usage(directory).free < row["size_bytes"] + 512 * 1024**2:
                reject(507, "REPLAY_STORAGE", "На сервере недостаточно места для сборки реплея.")
            with temporary.open("wb") as destination:
                os.chmod(temporary, 0o600)
                for number, part in enumerate(parts, 1):
                    path = directory / f"part-{number}"
                    if not path.is_file() or path.stat().st_size != part["size_bytes"]:
                        reject(409, "REPLAY_INTEGRITY", "Проверка целостности реплея не прошла.")
                    data = path.read_bytes()
                    if part["part_number"] != number or hashlib.sha256(data).hexdigest() != part["sha256"]:
                        reject(409, "REPLAY_INTEGRITY", "Проверка целостности реплея не прошла.")
                    destination.write(data)
                    digest.update(data)
                destination.flush()
                os.fsync(destination.fileno())
            try:
                metadata = parse_demo_metadata(temporary)
            except (ValueError, OSError):
                reject(400, "REPLAY_METADATA", "Не удалось прочитать реплей. Выберите полный исходный файл .dem.")
            source_digest = digest.hexdigest()
            player = _resolve_identity(connection, row, metadata, source_digest)
            os.replace(temporary, directory / "source.dem")
            row = connection.execute("""UPDATE replay_jobs SET state='queued',progress=0,
                source_sha256=%s,match_id=%s,account_id=%s,nickname=%s,updated_at=now()
                WHERE id=%s RETURNING *""", (source_digest, metadata["match_id"],
                    player["account_id"], player["nickname"], job_id)).fetchone()
        finally:
            temporary.unlink(missing_ok=True)
    # The durable source and committed state precede part removal. Retried
    # completion simply returns the same queued or processed job.
    for part in parts:
        (directory / f"part-{part['part_number']}").unlink(missing_ok=True)
    return {"replay": public(row)}


def delete_replay(job_id, owner_id):
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (owner_id,))
        row = connection.execute("SELECT id,account_id,match_id FROM replay_jobs WHERE id=%s AND owner_id=%s FOR UPDATE", (job_id, owner_id)).fetchone()
        if not row:
            reject(404, "REPLAY_NOT_FOUND", "Разбор не найден.")
        connection.execute("""UPDATE replay_jobs SET state='deleted',result_payload=NULL,
            lease_token=NULL,lease_expires_at=NULL,updated_at=now() WHERE id=%s""", (job_id,))
        connection.execute("DELETE FROM replay_parts WHERE job_id=%s", (job_id,))
        connection.execute("""DELETE FROM hero_pool_match_notes n
            WHERE n.owner_id=%s AND n.account_id=%s AND n.match_id=%s
              AND NOT EXISTS (SELECT 1 FROM replay_jobs r
                  WHERE r.owner_id=n.owner_id AND r.account_id=n.account_id
                    AND r.match_id=n.match_id AND r.state<>'deleted')""",
            (owner_id, row["account_id"], row["match_id"]))
    try:
        if replay_directory(job_id).exists():
            shutil.rmtree(replay_directory(job_id))
    except OSError:
        reject(503, "REPLAY_DELETE_PENDING", "Доступ к реплею закрыт. Повторите удаление, чтобы освободить место.")
    with database() as connection:
        connection.execute("UPDATE replay_jobs SET storage_deleted_at=now() WHERE id=%s AND state='deleted'", (job_id,))
    return {"deleted": True}


def heartbeat_replay_worker(worker_id):
    with database() as connection:
        connection.execute("""INSERT INTO replay_workers(id) VALUES (%s)
            ON CONFLICT(id) DO UPDATE SET last_seen=now()""", (worker_id,))


def claim_replay(worker_id, only_id=None):
    """Return a fenced processing row, or None. Retry only expired leases."""
    heartbeat_replay_worker(worker_id)
    with database() as connection:
        connection.execute("""UPDATE replay_jobs SET state='failed',failure_code='REPLAY_WORKER_INTERRUPTED',
            lease_token=NULL,lease_expires_at=NULL,updated_at=now()
            WHERE state='processing' AND lease_expires_at<now() AND attempt>=3""")
        row = connection.execute("""SELECT * FROM replay_jobs WHERE
            (state='queued' OR (state='processing' AND lease_expires_at<now()))
            AND attempt<3 AND (%s::uuid IS NULL OR id=%s::uuid)
            ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""", (only_id, only_id)).fetchone()
        if row is None:
            return None
        claimed = connection.execute("""UPDATE replay_jobs SET state='processing',progress=1,
            attempt=attempt+1,lease_token=%s,lease_expires_at=now()+make_interval(secs => %s),
            failure_code=NULL,updated_at=now() WHERE id=%s RETURNING *""",
            (uuid4(), LEASE_SECONDS, row["id"])).fetchone()
        archive = previous_report(connection, claimed)
        if archive:
            claimed["previous_report"] = archive["report"]
            claimed["previous_report_id"] = archive["id"]
        return claimed


def replay_progress(job_id, lease_token, progress):
    with database() as connection:
        row = connection.execute("""UPDATE replay_jobs SET progress=greatest(progress,%s),
            lease_expires_at=now()+make_interval(secs => %s),updated_at=now()
            WHERE id=%s AND lease_token=%s AND state='processing' AND lease_expires_at>now()
            RETURNING id""", (max(1, min(99, int(progress))), LEASE_SECONDS, job_id, lease_token)).fetchone()
    return bool(row)


def finish_replay(job_id, lease_token, report):
    """Persist only a fully parsed selected-player report from the worker.

    Required report identity is {match_id, player:{account_id}}. The API never
    accepts a report payload from the browser. Expired/stolen leases cannot
    publish after a retry or deletion.
    """
    if not isinstance(report, dict) or len(json.dumps(report, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESULT_BYTES:
        raise ValueError("REPLAY_RESULT_INVALID")
    with database() as connection:
        row = connection.execute("""SELECT * FROM replay_jobs WHERE id=%s AND state='processing'
            AND lease_token=%s AND lease_expires_at>now() FOR UPDATE""", (job_id, lease_token)).fetchone()
        if row is None:
            return False
        player = report.get("player")
        if (str(report.get("match_id")) != row["match_id"] or not isinstance(player, dict)
                or type(player.get("account_id")) is not int or player["account_id"] != row["account_id"]):
            raise ValueError("REPLAY_RESULT_IDENTITY")
        connection.execute("""UPDATE replay_jobs SET state='ready',progress=100,result_payload=%s,
            lease_token=NULL,lease_expires_at=NULL,failure_code=NULL,updated_at=now()
            WHERE id=%s""", (Jsonb(report), job_id))
    return True


def fail_replay(job_id, lease_token, code):
    if not re.fullmatch(r"REPLAY_[A-Z0-9_]{1,60}", code):
        code = "REPLAY_PARSE_FAILED"
    with database() as connection:
        row = connection.execute("""UPDATE replay_jobs SET state='failed',failure_code=%s,
            lease_token=NULL,lease_expires_at=NULL,updated_at=now()
            WHERE id=%s AND lease_token=%s AND state='processing' AND lease_expires_at>now()
            RETURNING id""", (code, job_id, lease_token)).fetchone()
    return bool(row)


def attach_replays(app):
    router = APIRouter(prefix="/api/replays")

    @router.get("")
    def listing(account=Depends(account_required)):
        return list_replays(account["owner_id"])

    @router.post("", status_code=201, dependencies=[Depends(csrf)])
    async def create(request: Request, account=Depends(account_required)):
        body = await json_body(request, CreateReplay)
        return await run_in_threadpool(create_replay, body, account["owner_id"])

    @router.get("/{job_id}")
    def detail(job_id: UUID, account=Depends(account_required)):
        return get_replay(job_id, account["owner_id"])

    @router.put("/{job_id}/parts/{part_number}", dependencies=[Depends(csrf)])
    async def part(job_id: UUID, part_number: int, request: Request, account=Depends(account_required)):
        # Check authorization before consuming the upload body.
        await run_in_threadpool(get_replay, job_id, account["owner_id"])
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > PART_BYTES):
            reject(413, "REPLAY_PART_SIZE", "Часть файла слишком велика.")
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > PART_BYTES:
                reject(413, "REPLAY_PART_SIZE", "Часть файла слишком велика.")
            data.extend(chunk)
        return await run_in_threadpool(store_part, job_id, part_number, bytes(data), account["owner_id"])

    @router.post("/{job_id}/complete", dependencies=[Depends(csrf)])
    def complete(job_id: UUID, account=Depends(account_required)):
        return complete_replay(job_id, account["owner_id"])

    @router.delete("/{job_id}", dependencies=[Depends(csrf)])
    def delete(job_id: UUID, account=Depends(account_required)):
        return delete_replay(job_id, account["owner_id"])

    app.include_router(router)
