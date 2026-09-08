"""Personal ChatGPT/Codex device authorization, never a shared customer credential.

Protocol follows NousResearch/hermes-agent's auth_codex.py at
9fd44b4dfc44138b9e5d5689acb56c438364ff7b (MIT): usercode -> poll authorization
code -> PKCE token exchange. Narma owns a separate explicit OAuth session.
Tokens are encrypted in PostgreSQL, bound to owner and connection generation;
no tokens are returned through HTTP or written to logs. Provider use is exposed
only through get_access_credentials(), which serializes refresh-token rotation.
"""
from __future__ import annotations

import base64
import asyncio
from datetime import datetime, timedelta, timezone
import json
import math
import os
import re
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Request
import httpx
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.concurrency import run_in_threadpool

from .db import database
from .web import account_required, csrf, reject

ISSUER = "https://auth.openai.com"
VERIFICATION_URL = ISSUER + "/codex/device"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"  # Public Codex OAuth client identifier.
USERCODE_URL = ISSUER + "/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = ISSUER + "/api/accounts/deviceauth/token"
TOKEN_URL = ISSUER + "/oauth/token"
DEVICE_TTL = 900
MAX_BODY = 16 * 1024
MAX_PROVIDER_BODY = 128 * 1024
UTC = timezone.utc
SAFE_CODES = frozenset({
    "CHATGPT_NOT_CONFIGURED", "CHATGPT_OWNER_ONLY", "CHATGPT_NOT_CONNECTED",
    "CHATGPT_AUTH_EXPIRED", "CHATGPT_AUTH_UNAVAILABLE", "CHATGPT_AUTH_RESPONSE",
    "CHATGPT_AUTH_REJECTED", "CHATGPT_AUTH_RATE_LIMIT", "CHATGPT_CONNECT_LIMIT",
    "CHATGPT_AUTH_CHANGED", "CHATGPT_AUTH_DECRYPT", "CHATGPT_QUOTA",
})


class AuthError(Exception):
    def __init__(self, code, status=503):
        self.code = code if code in SAFE_CODES else "CHATGPT_AUTH_UNAVAILABLE"
        self.status = status
        super().__init__(self.code)


def _now():
    return datetime.now(UTC)


def _fernet():
    try:
        return Fernet(os.environ.get("NARMA_CHATGPT_ENCRYPTION_KEY", "").encode("ascii"))
    except (ValueError, UnicodeError):
        raise AuthError("CHATGPT_NOT_CONFIGURED") from None


def configured():
    try:
        _fernet()
        return True
    except AuthError:
        return False


def _seal(owner_id, generation, payload):
    value = {"owner_id": owner_id, "generation": str(generation), "payload": payload}
    raw = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > 48 * 1024:
        raise AuthError("CHATGPT_AUTH_RESPONSE")
    return _fernet().encrypt(raw).decode("ascii")


def _open(row):
    try:
        value = json.loads(_fernet().decrypt(row["secret_ciphertext"].encode("ascii")))
        if (value.get("owner_id") != row["owner_id"]
                or value.get("generation") != str(row["generation"])
                or not isinstance(value.get("payload"), dict)):
            raise ValueError()
        return value["payload"]
    except (InvalidToken, ValueError, TypeError, UnicodeError, KeyError):
        raise AuthError("CHATGPT_AUTH_DECRYPT") from None


def _owner_allowed(connection, owner_id):
    designated = os.environ.get("NARMA_CHATGPT_OWNER_ID", "")
    if designated and owner_id != designated:
        return False
    owners = connection.execute("SELECT owner_id FROM portal_accounts ORDER BY owner_id LIMIT 2").fetchall()
    return len(owners) == 1 and owners[0]["owner_id"] == owner_id


def _require_owner(connection, owner_id):
    if not _owner_allowed(connection, owner_id):
        raise AuthError("CHATGPT_OWNER_ONLY", 403)


def _lock(connection, owner_id):
    # database() creates and closes one dedicated connection. A session lock
    # survives the durable pre-rotation commit and is released on close/crash.
    connection.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", ("chatgpt-auth:" + owner_id,))
    _require_owner(connection, owner_id)


def _row(connection, owner_id, *, lock=False):
    return connection.execute("SELECT * FROM chatgpt_connections WHERE owner_id=%s" +
                              (" FOR UPDATE" if lock else ""), (owner_id,)).fetchone()


def _paused(row, now=None):
    now = now or _now()
    return bool(row and row["quota_paused"] and
                (row["paused_until"] is None or row["paused_until"] > now))


def current_connection(connection, owner_id):
    """Read-only selection inside an existing job transaction; no decryption/network."""
    if not _owner_allowed(connection, owner_id):
        return None
    row = _row(connection, owner_id)
    if row is None:
        return None
    connected = row["state"] == "connected" and row["rotation_started_at"] is None
    return {"generation": str(row["generation"]), "connected": connected,
            "available": connected and configured() and not _paused(row),
            "quota_paused": _paused(row), "paused_until": row["paused_until"]}


def _public(owner_id, row):
    ready = configured()
    now = _now()
    state = row["state"] if row else "disconnected"
    if row and row["rotation_started_at"] is not None:
        state = "reconnect_required"
    if state == "pending" and row["expires_at"] <= now:
        state = "expired"
    result = {"provider": "openai-codex", "scope": "personal", "configured": ready,
        "can_connect": ready, "status": state if ready else "unavailable",
        "available": ready and state == "connected" and not _paused(row, now),
        "auth_generation": str(row["generation"]) if row else None,
        "connected_at": row["connected_at"] if row else None,
        "pending": None, "quota_paused": _paused(row, now),
        "paused_until": row["paused_until"] if row else None,
        "last_error_code": row["last_error_code"] if row else None}
    if state == "pending" and ready:
        try:
            secret = _open(row)
            result["pending"] = {"user_code": secret["user_code"],
                "verification_url": VERIFICATION_URL, "expires_at": row["expires_at"],
                "poll_interval_seconds": row["poll_interval_seconds"],
                "poll_after_seconds": max(1, math.ceil((row["next_poll_at"] - now).total_seconds()))}
        except (AuthError, KeyError):
            result.update(status="reconnect_required", last_error_code="CHATGPT_AUTH_DECRYPT")
    return result


def connection_status(owner_id):
    """Safe owner view, with a display-only device code while login is pending."""
    with database() as connection:
        _require_owner(connection, owner_id)
        return _public(owner_id, _row(connection, owner_id))


def enabled(owner_id):
    with database() as connection:
        value = current_connection(connection, owner_id)
        return bool(value and value["available"])


def credentials_current(owner_id, generation):
    with database() as connection:
        if not _owner_allowed(connection, owner_id):
            return False
        row = _row(connection, owner_id)
        return bool(row and row["state"] == "connected" and str(row["generation"]) == str(generation))


def _rotation_intent(connection, owner_id, kind):
    # If the process dies after a one-use grant has reached OpenAI, the next
    # process sees this marker and asks for a new login instead of replaying it.
    connection.execute("""UPDATE chatgpt_connections SET rotation_started_at=now(),
        rotation_kind=%s,updated_at=now() WHERE owner_id=%s""", (kind, owner_id))
    connection.commit()


def _oauth_post(url, *, json_body=None, form=None):
    if url not in {USERCODE_URL, DEVICE_TOKEN_URL, TOKEN_URL}:
        raise AuthError("CHATGPT_AUTH_REJECTED")

    async def request():
        # A per-read timeout alone permits an endless slow response. This outer
        # deadline covers headers, body, and decompression while owner lock is held.
        async with asyncio.timeout(20):
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
                async with client.stream("POST", url, json=json_body, data=form,
                                         headers={"Accept": "application/json"}) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_PROVIDER_BODY:
                            raise AuthError("CHATGPT_AUTH_RESPONSE")
                        raw.extend(chunk)
                    try:
                        body = json.loads(raw)
                    except (ValueError, UnicodeError):
                        body = {}
                    return response.status_code, body if isinstance(body, dict) else {}
    try:
        return asyncio.run(request())
    except (httpx.HTTPError, OSError, TimeoutError):
        raise AuthError("CHATGPT_AUTH_UNAVAILABLE") from None


def _provider_failure(status):
    if status == 429:
        return AuthError("CHATGPT_AUTH_RATE_LIMIT", 429)
    if status in {400, 401, 403}:
        return AuthError("CHATGPT_AUTH_REJECTED", 401)
    return AuthError("CHATGPT_AUTH_UNAVAILABLE")


def _bounded_text(value, maximum=16384):
    return isinstance(value, str) and 0 < len(value) <= maximum and not re.search(r"[\x00-\x20\x7f]", value)


def _claims(token):
    # Claims only supply refresh scheduling/account header. Provider validation,
    # not this unverified decode, is authoritative for token authentication.
    try:
        part = token.split(".")[1]
        value = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return value if isinstance(value, dict) else {}
    except (ValueError, IndexError, UnicodeError):
        return {}


def _tokens(body, *, old=None):
    access = body.get("access_token")
    refresh = body.get("refresh_token") or (old or {}).get("refresh_token")
    if not _bounded_text(access) or not _bounded_text(refresh):
        raise AuthError("CHATGPT_AUTH_RESPONSE")
    claims = _claims(access)
    auth = claims.get("https://api.openai.com/auth")
    account_id = auth.get("chatgpt_account_id") if isinstance(auth, dict) else None
    if account_id is None and old:
        account_id = old.get("account_id")
    if account_id is not None and not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,128}", str(account_id)):
        raise AuthError("CHATGPT_AUTH_RESPONSE")
    exp = claims.get("exp")
    now = _now().timestamp()
    if not isinstance(exp, (int, float)) or isinstance(exp, bool) or not math.isfinite(exp):
        duration = body.get("expires_in", 3600)
        duration = duration if isinstance(duration, int) and not isinstance(duration, bool) else 3600
        exp = now + min(max(duration, 60), 86400)
    if exp <= now or exp > now + 366 * 86400:
        raise AuthError("CHATGPT_AUTH_RESPONSE")
    return {"access_token": access, "refresh_token": refresh,
            "account_id": account_id, "access_expires_at": exp}


def _connect_limited(connection, owner_id):
    # Persisted before the upstream request; idempotently resuming a pending
    # flow never spends this bucket or requests another device grant.
    row = connection.execute("""INSERT INTO portal_auth_limits(bucket,attempts)
        VALUES (%s,1) ON CONFLICT(bucket) DO UPDATE SET
        attempts=CASE WHEN portal_auth_limits.window_started<now()-interval '15 minutes'
                      THEN 1 ELSE portal_auth_limits.attempts+1 END,
        window_started=CASE WHEN portal_auth_limits.window_started<now()-interval '15 minutes'
                      THEN now() ELSE portal_auth_limits.window_started END RETURNING attempts""",
        ("chatgpt-connect:" + owner_id,)).fetchone()
    return row["attempts"] > 5


def start_connection(owner_id):
    _fernet()
    failure = None
    with database() as connection:
        _lock(connection, owner_id)
        row = _row(connection, owner_id, lock=True)
        if row and row["rotation_started_at"] is not None:
            _clear(connection, owner_id, "reconnect_required", "CHATGPT_AUTH_EXPIRED")
            row = _row(connection, owner_id)
        if row and (row["state"] == "connected" or
                    (row["state"] == "pending" and row["expires_at"] > _now())):
            return _public(owner_id, row)
        if _connect_limited(connection, owner_id):
            failure = AuthError("CHATGPT_CONNECT_LIMIT", 429)
        else:
            try:
                status, body = _oauth_post(USERCODE_URL, json_body={"client_id": CLIENT_ID})
                if status != 200:
                    raise _provider_failure(status)
                if (not _bounded_text(body.get("device_auth_id"), 4096)
                        or not isinstance(body.get("user_code"), str)
                        or not re.fullmatch(r"[A-Za-z0-9-]{4,64}", body["user_code"])):
                    raise AuthError("CHATGPT_AUTH_RESPONSE")
                try:
                    interval = min(60, max(3, int(body.get("interval", 5))))
                except (ValueError, TypeError, OverflowError):
                    raise AuthError("CHATGPT_AUTH_RESPONSE") from None
                generation, now = uuid4(), _now()
                encrypted = _seal(owner_id, generation,
                    {"device_auth_id": body["device_auth_id"], "user_code": body["user_code"]})
                connection.execute("""INSERT INTO chatgpt_connections
                    (owner_id,generation,state,secret_ciphertext,expires_at,next_poll_at,poll_interval_seconds)
                    VALUES (%s,%s,'pending',%s,%s,%s,%s) ON CONFLICT(owner_id) DO UPDATE SET
                    generation=excluded.generation,state='pending',secret_ciphertext=excluded.secret_ciphertext,
                    expires_at=excluded.expires_at,next_poll_at=excluded.next_poll_at,
                    poll_interval_seconds=excluded.poll_interval_seconds,connected_at=NULL,
                    quota_paused=false,paused_until=NULL,last_error_code=NULL,
                    rotation_started_at=NULL,rotation_kind=NULL,updated_at=now()""",
                    (owner_id, generation, encrypted, now + timedelta(seconds=DEVICE_TTL),
                     now + timedelta(seconds=interval), interval))
            except AuthError as error:
                failure = error
        result = _public(owner_id, _row(connection, owner_id))
    if failure:
        raise failure
    return result


def _clear(connection, owner_id, state, code=None):
    connection.execute("""UPDATE chatgpt_connections SET state=%s,generation=%s,
        secret_ciphertext=NULL,expires_at=NULL,next_poll_at=NULL,connected_at=NULL,
        quota_paused=false,paused_until=NULL,last_error_code=%s,rotation_started_at=NULL,
        rotation_kind=NULL,updated_at=now() WHERE owner_id=%s""",
        (state, uuid4(), code, owner_id))


def poll_connection(owner_id, generation):
    _fernet()
    with database() as connection:
        _lock(connection, owner_id)
        row = _row(connection, owner_id, lock=True)
        if row and row["rotation_started_at"] is not None:
            _clear(connection, owner_id, "reconnect_required", "CHATGPT_AUTH_EXPIRED")
            row = _row(connection, owner_id)
        if not row or str(row["generation"]) != str(generation) or row["state"] != "pending":
            return _public(owner_id, row)
        if row["expires_at"] <= _now():
            _clear(connection, owner_id, "expired", "CHATGPT_AUTH_EXPIRED")
            return _public(owner_id, _row(connection, owner_id))
        if row["next_poll_at"] > _now():
            return _public(owner_id, row)
        connection.execute("""UPDATE chatgpt_connections SET next_poll_at=%s,updated_at=now()
            WHERE owner_id=%s""", (_now() + timedelta(seconds=row["poll_interval_seconds"]), owner_id))
        exchanging = False
        try:
            pending = _open(row)
            status, body = _oauth_post(DEVICE_TOKEN_URL, json_body={
                "device_auth_id": pending["device_auth_id"], "user_code": pending["user_code"]})
            if status in {403, 404}:
                return _public(owner_id, _row(connection, owner_id))
            if status != 200:
                raise _provider_failure(status)
            if (not _bounded_text(body.get("authorization_code"), 4096)
                    or not _bounded_text(body.get("code_verifier"), 4096)):
                raise AuthError("CHATGPT_AUTH_RESPONSE")
            # Lock spans polling and exchange: disconnect waits, then destroys
            # the result. A stale client cannot resurrect a cancelled generation.
            _rotation_intent(connection, owner_id, "exchange")
            exchanging = True
            status, body = _oauth_post(TOKEN_URL, form={"grant_type": "authorization_code",
                "code": body["authorization_code"], "code_verifier": body["code_verifier"],
                "redirect_uri": ISSUER + "/deviceauth/callback", "client_id": CLIENT_ID})
            if status != 200:
                # Authorization codes are single-use; do not retry uncertain exchange.
                _clear(connection, owner_id, "reconnect_required", _provider_failure(status).code)
                return _public(owner_id, _row(connection, owner_id))
            secret = _tokens(body)
            connection.execute("""UPDATE chatgpt_connections SET state='connected',
                secret_ciphertext=%s,connected_at=now(),expires_at=NULL,next_poll_at=NULL,
                quota_paused=false,paused_until=NULL,last_error_code=NULL,
                rotation_started_at=NULL,rotation_kind=NULL,updated_at=now()
                WHERE owner_id=%s AND generation=%s""",
                (_seal(owner_id, row["generation"], secret), owner_id, row["generation"]))
        except AuthError as error:
            # A one-use authorization code may have been consumed even if the
            # response was lost. Never retry an uncertain exchange implicitly.
            if exchanging or error.code in {"CHATGPT_AUTH_DECRYPT", "CHATGPT_AUTH_RESPONSE", "CHATGPT_AUTH_REJECTED"}:
                _clear(connection, owner_id, "reconnect_required", error.code)
            else:
                connection.execute("""UPDATE chatgpt_connections SET last_error_code=%s,
                    next_poll_at=%s,updated_at=now() WHERE owner_id=%s""",
                    (error.code, _now() + timedelta(seconds=60 if error.status == 429 else row["poll_interval_seconds"]), owner_id))
        return _public(owner_id, _row(connection, owner_id))


def disconnect(owner_id):
    with database() as connection:
        _lock(connection, owner_id)
        _clear(connection, owner_id, "disconnected")
        return _public(owner_id, _row(connection, owner_id))


def get_access_credentials(owner_id):
    """Server-only credentials; one refresh under the owner's persistent lock."""
    _fernet()
    failure, result = None, None
    with database() as connection:
        _lock(connection, owner_id)
        row = _row(connection, owner_id, lock=True)
        if row and row["rotation_started_at"] is not None:
            _clear(connection, owner_id, "reconnect_required", "CHATGPT_AUTH_EXPIRED")
            connection.commit()
            raise AuthError("CHATGPT_AUTH_EXPIRED", 401)
        if not row or row["state"] != "connected":
            raise AuthError("CHATGPT_NOT_CONNECTED", 409)
        if _paused(row):
            raise AuthError("CHATGPT_QUOTA", 429)
        if row["next_poll_at"] and row["next_poll_at"] > _now():
            raise AuthError("CHATGPT_AUTH_RATE_LIMIT", 429)
        refreshing = False
        try:
            secret = _open(row)
            if secret.get("access_expires_at", 0) <= _now().timestamp() + 60:
                _rotation_intent(connection, owner_id, "refresh")
                refreshing = True
                status, body = _oauth_post(TOKEN_URL, form={"grant_type": "refresh_token",
                    "refresh_token": secret["refresh_token"], "client_id": CLIENT_ID})
                if status != 200:
                    raise _provider_failure(status)
                secret = _tokens(body, old=secret)
                connection.execute("""UPDATE chatgpt_connections SET secret_ciphertext=%s,
                    next_poll_at=NULL,last_error_code=NULL,rotation_started_at=NULL,rotation_kind=NULL,
                    updated_at=now() WHERE owner_id=%s AND generation=%s""",
                    (_seal(owner_id, row["generation"], secret), owner_id, row["generation"]))
            result = {"access_token": secret["access_token"], "account_id": secret.get("account_id"),
                      "generation": str(row["generation"])}
        except AuthError as error:
            failure = error
            if refreshing and error.code == "CHATGPT_AUTH_RATE_LIMIT":
                connection.execute("""UPDATE chatgpt_connections SET next_poll_at=now()+interval '60 seconds',
                    last_error_code=%s,rotation_started_at=NULL,rotation_kind=NULL,
                    updated_at=now() WHERE owner_id=%s""", (error.code, owner_id))
            elif refreshing or error.code in {"CHATGPT_AUTH_REJECTED", "CHATGPT_AUTH_DECRYPT", "CHATGPT_AUTH_RESPONSE"}:
                _clear(connection, owner_id, "reconnect_required", "CHATGPT_AUTH_EXPIRED")
                failure = AuthError("CHATGPT_AUTH_EXPIRED", 401)
    if failure:
        raise failure
    return result


def record_provider_pause(owner_id, generation, seconds=None, code="CHATGPT_QUOTA"):
    """Pause only this login generation; unknown reset stays paused until reconnect."""
    code = code if code in SAFE_CODES else "CHATGPT_QUOTA"
    until = None
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and math.isfinite(seconds):
        until = _now() + timedelta(seconds=min(max(seconds, 30), 7 * 86400))
    with database() as connection:
        _lock(connection, owner_id)
        connection.execute("""UPDATE chatgpt_connections SET quota_paused=true,paused_until=%s,
            last_error_code=%s,updated_at=now() WHERE owner_id=%s AND generation=%s AND state='connected'""",
            (until, code, owner_id, generation))


def mark_reconnect_required(owner_id, generation):
    """An upstream 401/403 invalidates only the session used by that attempt."""
    with database() as connection:
        _lock(connection, owner_id)
        row = _row(connection, owner_id, lock=True)
        if row and row["state"] == "connected" and str(row["generation"]) == str(generation):
            _clear(connection, owner_id, "reconnect_required", "CHATGPT_AUTH_EXPIRED")


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PollBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auth_generation: UUID


async def _body(request, model):
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        reject(415, "CHATGPT_JSON", "Нужен JSON-запрос.")
    value = bytearray()
    async for chunk in request.stream():
        if len(value) + len(chunk) > MAX_BODY:
            reject(413, "CHATGPT_BODY", "Слишком большой запрос.")
        value.extend(chunk)
    try:
        return model.model_validate_json(value)
    except (ValidationError, ValueError):
        reject(400, "CHATGPT_FIELDS", "Обнови страницу и повтори подключение.")


def _http_call(function, *args):
    try:
        return function(*args)
    except AuthError as error:
        messages = {"CHATGPT_NOT_CONFIGURED": "Подключение ещё не настроено на сервере.",
            "CHATGPT_OWNER_ONLY": "Подключение доступно только владельцу платформы.",
            "CHATGPT_CONNECT_LIMIT": "Слишком много попыток. Повтори через 15 минут.",
            "CHATGPT_AUTH_RATE_LIMIT": "OpenAI временно ограничил попытки входа. Повтори позже.",
            "CHATGPT_AUTH_REJECTED": "OpenAI отклонил вход. Проверь доступ к авторизации устройства в аккаунте ChatGPT."}
        reject(error.status, error.code, messages.get(error.code, "Не удалось завершить подключение. Повтори позже."))


def attach_chatgpt(app):
    router = APIRouter(prefix="/api/integrations/chatgpt")

    @router.get("")
    def status(account=Depends(account_required)):
        return _http_call(connection_status, account["owner_id"])

    @router.post("/connect", dependencies=[Depends(csrf)])
    async def connect(request: Request, account=Depends(account_required)):
        await _body(request, EmptyBody)
        return await run_in_threadpool(_http_call, start_connection, account["owner_id"])

    @router.post("/poll", dependencies=[Depends(csrf)])
    async def poll(request: Request, account=Depends(account_required)):
        body = await _body(request, PollBody)
        return await run_in_threadpool(_http_call, poll_connection, account["owner_id"], body.auth_generation)

    @router.delete("", dependencies=[Depends(csrf)])
    async def remove(request: Request, account=Depends(account_required)):
        await _body(request, EmptyBody)
        return await run_in_threadpool(_http_call, disconnect, account["owner_id"])

    app.include_router(router)
