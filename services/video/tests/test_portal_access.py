"""Actual PostgreSQL transaction, role and credential-lifecycle boundaries."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from narma_video import portal_access, web
from narma_video.db import database
from test_web import ORIGIN, PASSWORD, portal, setup


def guest(portal):
    return TestClient(portal.app, base_url=ORIGIN, headers={"Origin": ORIGIN})


def invite(portal, email="guest@example.test"):
    response = portal.post("/api/auth/invitations", json={"email": email, "current_password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def accept(client, invitation, email="guest@example.test"):
    return client.post("/api/auth/accept-invitation", json={"email": email, "token": invitation["token"], "password": PASSWORD})


def codes(portal):
    response = portal.post("/api/auth/recovery-codes", json={"current_password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()["codes"]


def recover(client, code, email="owner@example.test", password=PASSWORD + " changed"):
    return client.post("/api/auth/recover", json={"email": email, "code": code, "new_password": password})


@pytest.mark.parametrize("existing", [0, 1, 2])
def test_migration_promotes_only_unambiguous_legacy_owner(portal, existing):
    schema = "synthetic_account_migration_" + uuid4().hex
    with database() as connection:
        # Generated identifier is fixed-prefix + UUID, never user-controlled.
        connection.execute(f'CREATE SCHEMA "{schema}"')
        connection.execute(f'SET LOCAL search_path TO "{schema}"')
        connection.execute("CREATE TABLE portal_accounts(owner_id text PRIMARY KEY)")
        for number in range(existing):
            connection.execute("INSERT INTO portal_accounts VALUES (%s)", (str(number),))
        connection.execute((Path(__file__).parent.parent / "migrations/023_portal_invites_recovery.sql").read_text())
        assert connection.execute("SELECT count(*) AS n FROM portal_accounts WHERE is_platform_owner").fetchone()["n"] == (1 if existing == 1 else 0)
        connection.execute("SET LOCAL search_path TO public")
        connection.execute(f'DROP SCHEMA "{schema}" CASCADE')


def test_invitation_is_email_bound_one_time_and_does_not_grant_owner(portal):
    setup(portal)
    assert portal.get("/api/session").json()["user"]["is_platform_owner"] is True
    invitation = invite(portal)
    assert "token" not in portal.get("/api/auth/invitations").text
    with database() as connection:
        stored = connection.execute("SELECT token_hash FROM portal_invitations").fetchone()["token_hash"]
    assert stored == portal_access.token_hash("invite", invitation["token"])
    visitor = guest(portal)
    assert accept(visitor, invitation, "wrong@example.test").status_code == 400
    assert accept(visitor, invitation, " Guest@Example.Test ").status_code == 201
    assert visitor.get("/api/session").json()["user"]["is_platform_owner"] is False
    assert accept(guest(portal), invitation).status_code == 400
    assert visitor.get("/api/auth/invitations").status_code == 403
    assert visitor.post("/api/auth/invitations", json={"email": "third@example.test", "current_password": PASSWORD}).status_code == 403
    assert visitor.request("DELETE", "/api/auth/invitations/" + invitation["invitation"]["id"], json={"current_password": PASSWORD}).status_code == 403
    assert guest(portal).post("/api/auth/invitations", json={"email": "third@example.test", "current_password": PASSWORD}).status_code == 401


def test_invitation_reauthentication_origin_expiry_rotation_and_revocation(portal):
    setup(portal)
    payload = {"email": "guest@example.test", "current_password": PASSWORD}
    assert portal.post("/api/auth/invitations", json={**payload, "current_password": "wrong"}).status_code == 403
    assert portal.post("/api/auth/invitations", json=payload, headers={"Origin": "https://evil.test"}).status_code == 403
    old = invite(portal)
    current = invite(portal)
    assert accept(guest(portal), old).status_code == 400
    visitor = guest(portal)
    assert visitor.post("/api/auth/accept-invitation", json={"email": payload["email"], "token": current["token"], "password": PASSWORD}, headers={"Origin": "https://evil.test"}).status_code == 403
    with database() as connection:
        connection.execute("UPDATE portal_invitations SET created_at=now()-interval '2 days',expires_at=now()-interval '1 day'")
    assert accept(visitor, current).status_code == 400
    renewed = invite(portal)
    response = portal.request("DELETE", "/api/auth/invitations/" + renewed["invitation"]["id"], json={"current_password": PASSWORD})
    assert response.status_code == 200
    assert accept(visitor, renewed).status_code == 400


def test_concurrent_invite_acceptance_creates_exactly_one_account(portal):
    setup(portal)
    invitation = invite(portal)
    gate = Barrier(2)
    def enter(_):
        gate.wait(timeout=10)
        return accept(guest(portal), invitation).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(enter, range(2))) == [201, 400]
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM portal_accounts").fetchone()["n"] == 2


def test_pending_invites_reserve_pilot_seats_and_can_be_renewed(portal, monkeypatch):
    monkeypatch.setattr(portal_access, "MAX_PILOT_ACCOUNTS", 3)
    setup(portal)
    first = invite(portal, "one@example.test")
    invite(portal, "two@example.test")
    invite(portal, "two@example.test")
    response = portal.post("/api/auth/invitations", json={"email": "three@example.test", "current_password": PASSWORD})
    assert response.status_code == 409
    assert accept(guest(portal), first, "one@example.test").status_code == 201
    assert portal.post("/api/auth/invitations", json={"email": "three@example.test", "current_password": PASSWORD}).status_code == 409


def test_recovery_hash_only_one_use_and_revokes_all_sessions(portal):
    setup(portal)
    other = guest(portal)
    assert other.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).status_code == 200
    saved = codes(portal)
    assert len(saved) == len(set(saved)) == 5
    assert portal.get("/api/auth/security").json() == {"recovery_codes_remaining": 5}
    with database() as connection:
        hashes = {row["token_hash"] for row in connection.execute("SELECT token_hash FROM portal_recovery_codes").fetchall()}
    assert hashes == {portal_access.token_hash("recovery", "owner@example.test\0" + code.replace("-", "")) for code in saved}
    assert portal.post("/api/auth/recovery-codes", json={"current_password": "wrong"}).status_code == 403
    assert recover(guest(portal), saved[0], email="other@example.test").status_code == 400
    assert recover(guest(portal), saved[0]).status_code == 200
    assert recover(guest(portal), saved[0]).status_code == 400
    assert portal.get("/api/session").json()["authenticated"] is False
    assert other.get("/api/session").json()["authenticated"] is False
    assert other.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).status_code == 401
    assert other.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD + " changed"}).status_code == 200
    assert other.get("/api/auth/security").json() == {"recovery_codes_remaining": 4}


def test_recovery_rotation_password_change_and_owner_invites(portal):
    setup(portal)
    old = codes(portal)
    saved = codes(portal)
    invitation = invite(portal)
    assert recover(guest(portal), old[0]).status_code == 400
    assert portal.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": PASSWORD + " changed"}).status_code == 200
    assert recover(guest(portal), saved[0]).status_code == 400
    assert accept(guest(portal), invitation).status_code == 400
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM portal_recovery_codes").fetchone()["n"] == 0


def test_recovering_owner_revokes_pending_invitations(portal):
    setup(portal)
    invitation = invite(portal)
    assert recover(guest(portal), codes(portal)[0]).status_code == 200
    assert accept(guest(portal), invitation).status_code == 400


def test_concurrent_recovery_consumes_code_once(portal):
    setup(portal)
    code = codes(portal)[0]
    gate = Barrier(2)
    def reset(_):
        gate.wait(timeout=10)
        return recover(guest(portal), code).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reset, range(2))) == [200, 400]
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM portal_sessions").fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) AS n FROM portal_recovery_codes WHERE used_at IS NOT NULL").fetchone()["n"] == 1


def test_stale_session_cannot_generate_recovery_after_revocation(portal):
    setup(portal)
    request = Request({"type": "http", "headers": [(b"cookie", (web.COOKIE + "=" + portal.cookies.get(web.COOKIE)).encode())], "client": ("testclient", 123)})
    account = web.session_account(request)
    with database() as connection:
        connection.execute("DELETE FROM portal_sessions")
    with pytest.raises(HTTPException) as error:
        portal_access.generate_recovery(request, account, portal_access.Reauthenticate(current_password=PASSWORD))
    assert error.value.status_code == 401
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM portal_recovery_codes").fetchone()["n"] == 0


def test_auth_rate_limits_allow_distinct_users_and_bound_rotation(portal):
    def req(address):
        return Request({"type": "http", "headers": [], "client": (address, 123)})
    # More than the old global cap of60 succeeds for distinct clients.
    for index in range(70):
        web.rate_limit(req(str(index)), "synthetic-growth", f"{index}@example.test")
    for index in range(10):
        web.rate_limit(req(str(index)), "synthetic-account", "target@example.test")
    with pytest.raises(HTTPException) as error:
        web.rate_limit(req("rotated-address"), "synthetic-account", "target@example.test")
    assert error.value.status_code == 429
    for index in range(60):
        web.rate_limit(req("same-address"), "synthetic-address", f"{index}@example.test")
    with pytest.raises(HTTPException):
        web.rate_limit(req("same-address"), "synthetic-address", "rotated@example.test")
