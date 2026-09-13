"""Closed-pilot invitations and offline, one-use account recovery.

Only hashes are stored. Raw invitation/recovery credentials are returned once
in no-store responses and never sent to an email service or written to logs.
All password/session mutations share web.py's per-account transaction lock.
"""
import hashlib
import re
import secrets
from uuid import UUID, uuid4

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .db import database

MAX_PILOT_ACCOUNTS = 25
RECOVERY_CODE_COUNT = 5


class Reauthenticate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=256)


class Invite(Reauthenticate):
    email: str = Field(min_length=3, max_length=254)


class AcceptInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    password: str = Field(min_length=12, max_length=256)


class Recover(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=32, max_length=64)
    new_password: str = Field(min_length=12, max_length=256)


def token_hash(kind, value):
    return hashlib.sha256((kind + "\0" + value).encode()).hexdigest()


def reauthenticated(connection, request, account, password, *, owner_only=False):
    from . import web
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (account["owner_id"],))
    row = connection.execute("SELECT * FROM portal_accounts WHERE owner_id=%s FOR UPDATE", (account["owner_id"],)).fetchone()
    # Recheck the session under the password-mutation lock: a request queued
    # behind a reset must not keep using its already-resolved dependency.
    session = connection.execute("SELECT 1 FROM portal_sessions WHERE owner_id=%s AND token_hash=%s AND expires_at>now()",
        (account["owner_id"], hashlib.sha256(request.cookies.get(web.COOKIE, "").encode()).hexdigest())).fetchone()
    if not row or not session:
        web.reject(401, "PORTAL_SIGN_IN", "Войдите в аккаунт заново.")
    if owner_only and not row["is_platform_owner"]:
        web.reject(403, "PORTAL_OWNER_REQUIRED", "Приглашения доступны владельцу платформы.")
    if not web.password_matches(password, row["password_hash"]):
        web.reject(403, "PORTAL_PASSWORD", "Текущий пароль неверен.")
    return row


def create_invitation(request, account, body):
    from . import web
    web.rate_limit(request, "invite", account["email"])
    email = web.email_normalized(body.email)
    token = secrets.token_urlsafe(32)
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (web.PORTAL_LOCK,))
        reauthenticated(connection, request, account, body.current_password, owner_only=True)
        if connection.execute("SELECT 1 FROM portal_accounts WHERE email=%s", (email,)).fetchone():
            web.reject(409, "PORTAL_INVITE_EXISTS", "Аккаунт с этой почтой уже существует.")
        accounts = connection.execute("SELECT count(*) AS n FROM portal_accounts").fetchone()["n"]
        pending = connection.execute("SELECT count(*) AS n FROM portal_invitations WHERE used_at IS NULL AND expires_at>now() AND email<>%s", (email,)).fetchone()["n"]
        if accounts + pending >= MAX_PILOT_ACCOUNTS:
            web.reject(409, "PORTAL_PILOT_FULL", "Лимит участников теста достигнут. Отзовите неиспользованное приглашение.")
        row = connection.execute("""INSERT INTO portal_invitations(id,email,token_hash,invited_by,expires_at)
            VALUES (%s,%s,%s,%s,now()+interval '24 hours')
            ON CONFLICT(email) DO UPDATE SET id=excluded.id,token_hash=excluded.token_hash,
              invited_by=excluded.invited_by,created_at=now(),expires_at=excluded.expires_at,used_at=NULL
            RETURNING id,email,expires_at""", (uuid4(), email, token_hash("invite", token), account["owner_id"])).fetchone()
    return {"invitation": row, "token": token}


def accept_invitation(request, body):
    from . import web
    email = web.email_normalized(body.email)
    web.rate_limit(request, "accept", email)
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (web.PORTAL_LOCK,))
        invitation = connection.execute("""SELECT * FROM portal_invitations
            WHERE token_hash=%s AND email=%s AND used_at IS NULL AND expires_at>now() FOR UPDATE""",
            (token_hash("invite", body.token), email)).fetchone()
        if not invitation or connection.execute("SELECT 1 FROM portal_accounts WHERE email=%s", (email,)).fetchone():
            web.reject(400, "PORTAL_INVITE_INVALID", "Приглашение недействительно, уже использовано или вы указали другую почту.")
        if connection.execute("SELECT count(*) AS n FROM portal_accounts").fetchone()["n"] >= MAX_PILOT_ACCOUNTS:
            web.reject(409, "PORTAL_PILOT_FULL", "Приём участников временно приостановлен.")
        account = connection.execute("""INSERT INTO portal_accounts(owner_id,email,password_hash)
            VALUES (%s,%s,%s) RETURNING owner_id,email""", ("portal_" + uuid4().hex, email, web.password_hash(body.password))).fetchone()
        connection.execute("UPDATE portal_invitations SET used_at=now() WHERE id=%s", (invitation["id"],))
        return web.with_session(connection, account, 201)


def revoke_invitation(request, account, body, invitation_id):
    from . import web
    web.rate_limit(request, "invite", account["email"])
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (web.PORTAL_LOCK,))
        reauthenticated(connection, request, account, body.current_password, owner_only=True)
        connection.execute("DELETE FROM portal_invitations WHERE id=%s AND invited_by=%s AND used_at IS NULL", (invitation_id, account["owner_id"]))
    return {"revoked": True}


def generate_recovery(request, account, body):
    from . import web
    web.rate_limit(request, "recovery_generate", account["email"])
    codes = [secrets.token_hex(16) for _ in range(RECOVERY_CODE_COUNT)]
    with database() as connection:
        reauthenticated(connection, request, account, body.current_password)
        connection.execute("DELETE FROM portal_recovery_codes WHERE owner_id=%s", (account["owner_id"],))
        for code in codes:
            connection.execute("INSERT INTO portal_recovery_codes(token_hash,owner_id) VALUES (%s,%s)",
                (token_hash("recovery", account["email"] + "\0" + code), account["owner_id"]))
    return {"codes": ["-".join(code[i:i+8] for i in range(0, 32, 8)) for code in codes]}


def recover_account(request, body):
    from . import web
    email = web.email_normalized(body.email)
    web.rate_limit(request, "recover", email)
    code = re.sub(r"[\s-]", "", body.code).lower()
    digest = token_hash("recovery", email + "\0" + code)
    with database() as connection:
        account = connection.execute("SELECT owner_id,email FROM portal_accounts WHERE email=%s", (email,)).fetchone()
        if account:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (account["owner_id"],))
        recovery = connection.execute("SELECT token_hash FROM portal_recovery_codes WHERE owner_id=%s AND token_hash=%s AND used_at IS NULL FOR UPDATE",
            (account["owner_id"] if account else "", digest)).fetchone()
        if not account or not recovery or not re.fullmatch(r"[0-9a-f]{32}", code):
            web.reject(400, "PORTAL_RECOVERY_INVALID", "Проверьте почту и резервный код. Каждый код можно использовать только один раз.")
        connection.execute("UPDATE portal_recovery_codes SET used_at=now() WHERE token_hash=%s", (digest,))
        connection.execute("UPDATE portal_accounts SET password_hash=%s WHERE owner_id=%s", (web.password_hash(body.new_password), account["owner_id"]))
        connection.execute("DELETE FROM portal_sessions WHERE owner_id=%s", (account["owner_id"],))
        connection.execute("DELETE FROM portal_invitations WHERE invited_by=%s AND used_at IS NULL", (account["owner_id"],))
    # Recovery never silently logs in or grants platform authority.
    return {"authenticated": False, "password_changed": True}


def attach(router):
    from . import web

    @router.get("/auth/security")
    def security(account=Depends(web.account_required)):
        with database() as connection:
            count = connection.execute("SELECT count(*) AS n FROM portal_recovery_codes WHERE owner_id=%s AND used_at IS NULL", (account["owner_id"],)).fetchone()["n"]
        return {"recovery_codes_remaining": count}

    @router.get("/auth/invitations")
    def invitations(account=Depends(web.account_required)):
        if not account["is_platform_owner"]:
            web.reject(403, "PORTAL_OWNER_REQUIRED", "Приглашения доступны владельцу платформы.")
        with database() as connection:
            rows = connection.execute("SELECT id,email,expires_at FROM portal_invitations WHERE invited_by=%s AND used_at IS NULL AND expires_at>now() ORDER BY created_at DESC", (account["owner_id"],)).fetchall()
        return {"invitations": rows, "maximum_accounts": MAX_PILOT_ACCOUNTS}

    @router.post("/auth/invitations", dependencies=[Depends(web.csrf)])
    async def invite(request: Request, account=Depends(web.account_required)):
        return await run_in_threadpool(create_invitation, request, account, await web.json_body(request, Invite))

    @router.delete("/auth/invitations/{invitation_id}", dependencies=[Depends(web.csrf)])
    async def revoke(invitation_id: UUID, request: Request, account=Depends(web.account_required)):
        return await run_in_threadpool(revoke_invitation, request, account, await web.json_body(request, Reauthenticate), invitation_id)

    @router.post("/auth/accept-invitation", dependencies=[Depends(web.csrf)])
    async def accept(request: Request):
        return await run_in_threadpool(accept_invitation, request, await web.json_body(request, AcceptInvite))

    @router.post("/auth/recovery-codes", dependencies=[Depends(web.csrf)])
    async def generate(request: Request, account=Depends(web.account_required)):
        return await run_in_threadpool(generate_recovery, request, account, await web.json_body(request, Reauthenticate))

    @router.post("/auth/recover", dependencies=[Depends(web.csrf)])
    async def recover(request: Request):
        return await run_in_threadpool(recover_account, request, await web.json_body(request, Recover))
