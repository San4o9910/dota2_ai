"""Standalone browser boundary. No caller-supplied owner or provider credential.

Mount with ``attach_web(app)`` after existing private API routes. Browser calls
reuse those typed handlers directly, so their owner checks, streaming source
responses, upload limits and billing gate remain authoritative.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .config import MAX_VIDEO_BYTES, media_root
from .db import database
from .replay_metadata import parse_demo_metadata, resolve_player

COOKIE = "__Host-narma_session"
SESSION_SECONDS = 7 * 24 * 3600
MAX_REPLAY_BYTES = 512 * 1024**2
UPLOAD_GLOBAL_BYTES = 2 * MAX_REPLAY_BYTES
PORTAL_LOCK = 643847209
_DUMMY_SALT = b"narma-login-dummy-salt-v1"
_KDF_SLOTS = threading.BoundedSemaphore(2)


def _derive_password(password: str, salt: bytes):
    # FastAPI's thread pool is larger than the API container's memory budget.
    # At most two 32 MiB KDFs may run concurrently, including unknown accounts.
    with _KDF_SLOTS:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=32768, r=8,
                              p=1, dklen=32, maxmem=64 * 1024**2)


def origin():
    value = os.environ.get("APP_ORIGIN", "")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment
            or value != f"https://{parsed.netloc}"):
        raise RuntimeError("APP_ORIGIN must be one exact HTTPS origin")
    return value


def reject(status, code, message):
    raise HTTPException(status, message, headers={"X-Narma-Error": code})


def csrf(request: Request):
    if request.headers.get("origin") != origin():
        reject(403, "PORTAL_ORIGIN", "Откройте страницу на адресе платформы и повторите действие.")
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site and fetch_site != "same-origin":
        reject(403, "PORTAL_ORIGIN", "Запрос с другого сайта отклонён.")


def password_hash(password: str):
    salt = secrets.token_bytes(16)
    value = _derive_password(password, salt)
    return "scrypt$32768$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(value).decode()


def password_matches(password: str, stored: str | None):
    try:
        scheme, n, r, p, salt64, digest64 = (stored or "").split("$")
        if (scheme, n, r, p) != ("scrypt", "32768", "8", "1"):
            raise ValueError("Unsupported password hash")
        salt = base64.b64decode(salt64, validate=True)
        expected = base64.b64decode(digest64, validate=True)
        if len(salt) != 16 or len(expected) != 32:
            raise ValueError("Invalid password hash")
    except (ValueError, TypeError):
        salt, expected = _DUMMY_SALT, bytes(32)
    actual = _derive_password(password, salt)
    return stored is not None and hmac.compare_digest(expected, actual)


def email_normalized(email: str):
    value = email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) or len(value) > 254:
        reject(400, "PORTAL_EMAIL", "Введите адрес электронной почты.")
    return value


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class Setup(Credentials):
    token: str = Field(min_length=32, max_length=128)


class ChangePassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class BrowserVideo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    filename: str = Field(min_length=5, max_length=180)
    size_bytes: int = Field(ge=16, le=MAX_VIDEO_BYTES)


async def json_body(request: Request, model):
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        reject(415, "PORTAL_JSON", "Нужен JSON-запрос.")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 8192:
            reject(413, "PORTAL_BODY", "Слишком большой запрос.")
        data.extend(chunk)
    try:
        return model.model_validate_json(data)
    except (ValidationError, ValueError):
        reject(400, "PORTAL_FIELDS", "Проверьте поля формы. Пароль должен содержать от 12 до 256 символов.")


def rate_limit(request: Request, purpose: str, email: str = ""):
    # Never use browser-provided forwarding headers. Nginx/uvicorn must be
    # configured to trust only the local reverse proxy; a shared global bucket
    # also bounds attacks if the source address is unavailable or rotated.
    address = request.client.host if request.client else "unknown"
    identity = hashlib.sha256((purpose + "\0" + address + "\0" + email).encode()).hexdigest()
    buckets = [("global-" + purpose, 60, 900), (identity, 10, 900)]
    blocked = False
    with database() as connection:
        for bucket, maximum, seconds in buckets:
            row = connection.execute("""
                INSERT INTO portal_auth_limits(bucket, attempts) VALUES (%s, 1)
                ON CONFLICT(bucket) DO UPDATE SET
                    attempts=CASE WHEN portal_auth_limits.window_started < now() - make_interval(secs => %s)
                                  THEN 1 ELSE portal_auth_limits.attempts+1 END,
                    window_started=CASE WHEN portal_auth_limits.window_started < now() - make_interval(secs => %s)
                                        THEN now() ELSE portal_auth_limits.window_started END
                RETURNING attempts
                """, (bucket, seconds, seconds)).fetchone()
            blocked = blocked or row["attempts"] > maximum
            if blocked:
                break
        connection.execute("DELETE FROM portal_auth_limits WHERE window_started < now()-interval '1 day'")
    if blocked:
        reject(429, "PORTAL_LOGIN_LIMIT", "Слишком много попыток. Повторите через 15 минут.")


def session_account(request: Request):
    token = request.cookies.get(COOKIE, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return None
    with database() as connection:
        return connection.execute("""SELECT a.owner_id,a.email FROM portal_sessions s
            JOIN portal_accounts a ON a.owner_id=s.owner_id
            WHERE s.token_hash=%s AND s.expires_at>now()""",
            (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()


def account_required(request: Request):
    account = session_account(request)
    if account is None:
        reject(401, "PORTAL_SIGN_IN", "Войдите в аккаунт.")
    return account


def profile_for(owner_id):
    with database() as connection:
        row = connection.execute("""SELECT account_id,nickname,match_id,hero_name,side,bound_at
            FROM portal_dota_profiles WHERE owner_id=%s""", (owner_id,)).fetchone()
    return row


def with_session(connection, account, status=200):
    token = secrets.token_urlsafe(32)
    connection.execute("DELETE FROM portal_sessions WHERE expires_at<=now()")
    connection.execute("""DELETE FROM portal_sessions WHERE token_hash IN
        (SELECT token_hash FROM portal_sessions WHERE owner_id=%s ORDER BY created_at DESC OFFSET 4)""", (account["owner_id"],))
    connection.execute("""INSERT INTO portal_sessions(token_hash,owner_id,expires_at)
        VALUES (%s,%s,now()+make_interval(secs => %s))""",
        (hashlib.sha256(token.encode()).hexdigest(), account["owner_id"], SESSION_SECONDS))
    response = JSONResponse({"authenticated": True, "user": {"email": account["email"]}}, status_code=status)
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, secure=True, httponly=True, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


def setup_account(request, body):
    rate_limit(request, "setup")
    expected = os.environ.get("PORTAL_SETUP_TOKEN_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        reject(503, "PORTAL_SETUP_DISABLED", "Первичная настройка недоступна.")
    try:
        expires = datetime.fromisoformat(os.environ.get("PORTAL_SETUP_EXPIRES_AT", "").replace("Z", "+00:00"))
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
            raise ValueError("Expired setup")
    except ValueError:
        reject(403, "PORTAL_SETUP_EXPIRED", "Срок ссылки настройки истёк. Нужна новая ссылка владельца.")
    if not hmac.compare_digest(hashlib.sha256(body.token.encode()).hexdigest(), expected):
        reject(403, "PORTAL_SETUP_TOKEN", "Ссылка настройки недействительна.")
    email = email_normalized(body.email)
    hashed = password_hash(body.password)
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (PORTAL_LOCK,))
        if connection.execute("SELECT 1 FROM portal_accounts LIMIT 1").fetchone():
            reject(409, "PORTAL_SETUP_COMPLETE", "Аккаунт уже создан. Войдите с вашим паролем.")
        account = connection.execute("""INSERT INTO portal_accounts(owner_id,email,password_hash)
            VALUES (%s,%s,%s) RETURNING owner_id,email""", ("portal_" + uuid4().hex, email, hashed)).fetchone()
        return with_session(connection, account, 201)


def login_account(request, body):
    email = email_normalized(body.email)
    rate_limit(request, "login", email)
    with database() as connection:
        account = connection.execute("SELECT owner_id FROM portal_accounts WHERE email=%s", (email,)).fetchone()
        if account:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (account["owner_id"],))
            # Read the hash only after the same lock used by password changes;
            # an old-password login cannot create a session after revocation.
            account = connection.execute("SELECT owner_id,email,password_hash FROM portal_accounts WHERE owner_id=%s", (account["owner_id"],)).fetchone()
        valid = password_matches(body.password, account["password_hash"] if account else None)
        if not account or not valid:
            reject(401, "PORTAL_CREDENTIALS", "Неверный адрес почты или пароль.")
        return with_session(connection, account)


def change_password(request, account, body):
    rate_limit(request, "password", account["email"])
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (account["owner_id"],))
        row = connection.execute("SELECT password_hash FROM portal_accounts WHERE owner_id=%s FOR UPDATE", (account["owner_id"],)).fetchone()
        if not row or not password_matches(body.current_password, row["password_hash"]):
            reject(401, "PORTAL_PASSWORD", "Текущий пароль неверен.")
        connection.execute("UPDATE portal_accounts SET password_hash=%s WHERE owner_id=%s", (password_hash(body.new_password),account["owner_id"]))
        connection.execute("DELETE FROM portal_sessions WHERE owner_id=%s", (account["owner_id"],))
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response


def reserve_upload(owner_id, upload_id):
    root = media_root() / "profile-uploads"
    root.mkdir(mode=0o700, exist_ok=True)
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (PORTAL_LOCK + 1,))
        # Expired uploads cannot be valid clients; remove only our UUID temp
        # names and reservations, never arbitrary media or worker files.
        stale = connection.execute("DELETE FROM portal_replay_uploads WHERE expires_at<now() RETURNING id").fetchall()
        for row in stale:
            (root / (str(row["id"]) + ".dem")).unlink(missing_ok=True)
        reserved = connection.execute("SELECT coalesce(sum(reserved_bytes),0) AS bytes,count(*) FILTER (WHERE owner_id=%s) AS own FROM portal_replay_uploads", (owner_id,)).fetchone()
        if reserved["own"] or reserved["bytes"] + MAX_REPLAY_BYTES > UPLOAD_GLOBAL_BYTES:
            reject(429, "PORTAL_REPLAY_BUSY", "Дождитесь завершения текущей загрузки.")
        if shutil.disk_usage(root).free < MAX_REPLAY_BYTES + 1024**3:
            reject(507, "PORTAL_STORAGE", "Недостаточно места для реплея. Повторите позже.")
        connection.execute("INSERT INTO portal_replay_uploads(id,owner_id,reserved_bytes,expires_at) VALUES (%s,%s,%s,now()+interval '30 minutes')", (upload_id,owner_id,MAX_REPLAY_BYTES))
    return root / (str(upload_id) + ".dem")


def bind_replay(owner_id, metadata, nickname, digest):
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (owner_id,))
        current = connection.execute("SELECT account_id FROM portal_dota_profiles WHERE owner_id=%s FOR UPDATE", (owner_id,)).fetchone()
        try:
            player = resolve_player(metadata, nickname, current["account_id"] if current else None)
        except ValueError as error:
            code = getattr(error, "code", "DOTA_PLAYER_NOT_FOUND")
            messages = {
                "DOTA_PLAYER_AMBIGUOUS": "В реплее несколько игроков с этим ником.",
                "DOTA_PLAYER_NOT_FOUND": "В реплее нет игрока с таким ником. Укажите ник из этого матча.",
                "DOTA_PLAYER_IDENTITY_UNAVAILABLE": "В метаданных нет идентификатора Steam этого игрока.",
                "DOTA_PROFILE_LOCKED": "К аккаунту уже привязан другой игрок. Выберите реплей вашего игрока.",
            }
            reject(409 if code == "DOTA_PROFILE_LOCKED" else 400, code, messages.get(code, "Не удалось определить игрока по реплею."))
        row = connection.execute("""INSERT INTO portal_dota_profiles
            (owner_id,account_id,nickname,match_id,hero_name,side,source_sha256)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(owner_id) DO UPDATE SET nickname=excluded.nickname,match_id=excluded.match_id,
                hero_name=excluded.hero_name,side=excluded.side,source_sha256=excluded.source_sha256,updated_at=now()
            RETURNING account_id,nickname,match_id,hero_name,side,bound_at""",
            (owner_id,player["account_id"],player["nickname"],metadata["match_id"],player["hero_name"],player["side"],digest)).fetchone()
    return {"profile": row}


def attach_web(app):
    from . import api
    router = APIRouter(prefix="/api")

    @router.get("/session")
    def session(request: Request):
        account = session_account(request)
        with database() as connection:
            configured = bool(connection.execute("SELECT 1 FROM portal_accounts LIMIT 1").fetchone())
        return {"authenticated": bool(account), "setup_required": not configured,
                "user": {"email": account["email"]} if account else None,
                "profile": profile_for(account["owner_id"]) if account else None}

    @router.post("/auth/setup", dependencies=[Depends(csrf)])
    async def setup(request: Request):
        return await run_in_threadpool(setup_account, request, await json_body(request, Setup))

    @router.post("/auth/login", dependencies=[Depends(csrf)])
    async def login(request: Request):
        return await run_in_threadpool(login_account, request, await json_body(request, Credentials))

    @router.post("/auth/password", dependencies=[Depends(csrf)])
    async def password(request: Request, account=Depends(account_required)):
        return await run_in_threadpool(change_password, request, account, await json_body(request, ChangePassword))

    @router.post("/auth/logout", dependencies=[Depends(csrf)])
    def logout(request: Request, account=Depends(account_required)):
        token = request.cookies.get(COOKIE, "")
        with database() as connection:
            connection.execute("DELETE FROM portal_sessions WHERE token_hash=%s AND owner_id=%s", (hashlib.sha256(token.encode()).hexdigest(),account["owner_id"]))
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response

    @router.get("/profile")
    def profile(account=Depends(account_required)):
        return {"profile": profile_for(account["owner_id"])}

    @router.post("/profile/replay", dependencies=[Depends(csrf)])
    async def replay(request: Request, account=Depends(account_required)):
        # Raw bytes keep memory bounded and avoid an unbounded multipart spool.
        try:
            nickname = unquote(request.headers.get("x-dota-nickname", ""), errors="strict").strip()
        except UnicodeError:
            reject(400, "DOTA_NICKNAME", "Не удалось прочитать ник игрока.")
        if not nickname or len(nickname) > 128 or any(ord(c) < 32 for c in nickname):
            reject(400, "DOTA_NICKNAME", "Укажите ник из загружаемого реплея.")
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_REPLAY_BYTES):
            reject(413, "PORTAL_REPLAY_SIZE", "Размер реплея должен быть не больше 512 МБ.")
        upload_id = uuid4()
        path = await run_in_threadpool(reserve_upload, account["owner_id"], upload_id)
        total, digest, started = 0, hashlib.sha256(), time.monotonic()
        try:
            with path.open("xb") as destination:
                os.chmod(path, 0o600)
                async for chunk in request.stream():
                    if time.monotonic() - started > 25 * 60:
                        reject(408, "PORTAL_REPLAY_TIMEOUT", "Загрузка заняла слишком много времени. Повторите её.")
                    total += len(chunk)
                    if total > MAX_REPLAY_BYTES:
                        reject(413, "PORTAL_REPLAY_SIZE", "Размер реплея должен быть не больше 512 МБ.")
                    await run_in_threadpool(destination.write, chunk)
                    digest.update(chunk)
            if length and total != int(length):
                reject(400, "PORTAL_REPLAY_INCOMPLETE", "Реплей передан не полностью.")
            try:
                metadata = await run_in_threadpool(parse_demo_metadata, path)
            except (ValueError, OSError):
                reject(400, "DOTA_REPLAY_METADATA_UNAVAILABLE", "Не удалось прочитать реплей Dota 2. Выберите исходный файл .dem.")
            return await run_in_threadpool(bind_replay, account["owner_id"], metadata, nickname, digest.hexdigest())
        finally:
            path.unlink(missing_ok=True)
            with database() as connection:
                connection.execute("DELETE FROM portal_replay_uploads WHERE id=%s AND owner_id=%s", (upload_id,account["owner_id"]))

    @router.get("/videos")
    def videos(account=Depends(account_required)):
        return api.videos(account["owner_id"])

    @router.post("/videos", status_code=201, dependencies=[Depends(csrf)])
    async def create(request: Request, account=Depends(account_required)):
        body = await json_body(request, BrowserVideo)
        profile = await run_in_threadpool(profile_for, account["owner_id"])
        if profile is None:
            reject(409, "DOTA_PROFILE_REQUIRED", "Сначала закрепите игрока с помощью реплея .dem.")
        command = api.CreateVideo(**body.model_dump(), account_id=profile["account_id"], nickname=profile["nickname"])
        return await run_in_threadpool(api.create_video, command, account["owner_id"])

    @router.get("/videos/{job_id}")
    def detail(job_id: UUID, after: int = -1, account=Depends(account_required)):
        return api.get_video(job_id, account["owner_id"], after)

    @router.put("/videos/{job_id}/parts/{part_number}", dependencies=[Depends(csrf)])
    async def part(job_id: UUID, part_number: int, request: Request, account=Depends(account_required)):
        return await api.upload_part(job_id, part_number, request, account["owner_id"])

    @router.post("/videos/{job_id}/complete", dependencies=[Depends(csrf)])
    def complete(job_id: UUID, account=Depends(account_required)):
        return api.complete_video(job_id, account["owner_id"])

    @router.get("/videos/{job_id}/source")
    def source(job_id: UUID, account=Depends(account_required)):
        return api.source(job_id, account["owner_id"])

    @router.delete("/videos/{job_id}", dependencies=[Depends(csrf)])
    def delete(job_id: UUID, account=Depends(account_required)):
        return api.delete_video(job_id, account["owner_id"])

    app.include_router(router)

    @app.middleware("http")
    async def browser_security(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response
