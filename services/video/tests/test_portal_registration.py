"""Registration admission and account isolation against real PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from narma_video import portal_access, web
from narma_video.db import database
from test_portal_access import guest, invite, accept
from test_web import PASSWORD, portal, profile_seed, setup


def register(client, email="new@example.test", **changes):
    body = {"email": email, "password": PASSWORD, "password_confirmation": PASSWORD}
    return client.post("/api/auth/register", json={**body, **changes})


def test_signup_requires_configured_owner_and_never_bootstraps_admin(portal):
    assert portal.get("/api/session").json()["registration_available"] is False
    response = register(portal)
    assert response.status_code == 503
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM portal_accounts").fetchone()["n"] == 0
    setup(portal)
    assert portal.get("/api/session").json()["registration_available"] is True
    with database() as connection:
        connection.execute("UPDATE portal_accounts SET is_platform_owner=false")
    assert register(guest(portal), "other@example.test").status_code == 503


def test_signup_is_private_and_preserves_old_accounts_and_money(portal):
    from narma_video.replay_jobs import attach_replays
    attach_replays(portal.app)
    setup(portal)
    owner = profile_seed()
    job = uuid4()
    with database() as connection:
        connection.execute("""INSERT INTO replay_jobs(id,owner_id,filename,size_bytes,requested_nickname,nickname)
            VALUES (%s,%s,'old.dem',20,'SyntheticPlayer','SyntheticPlayer')""", (job, owner))
        before = [connection.execute("SELECT * FROM " + table).fetchall()
                  for table in ("openai_api_budget", "openai_api_calls", "video_ai_budget", "video_provider_calls")]
    visitor = guest(portal)
    response = register(visitor, " New@Example.Test ")
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    assert all(value in cookie for value in ("__Host-narma_session=", "Secure", "HttpOnly", "SameSite=strict"))
    state = visitor.get("/api/session").json()
    assert state["user"] == {"email": "new@example.test", "is_platform_owner": False}
    assert state["profile"] is None
    listing = visitor.get("/api/replays")
    assert listing.status_code == 200, listing.text
    assert listing.json()["replays"] == []
    assert portal.get(f"/api/replays/{job}").status_code == 200
    assert visitor.get(f"/api/replays/{job}").status_code == 404
    assert visitor.get("/api/auth/invitations").status_code == 403
    assert portal.get("/api/profile").json()["profile"]["nickname"] == "SyntheticPlayer"
    with database() as connection:
        account = connection.execute("SELECT * FROM portal_accounts WHERE email='new@example.test'").fetchone()
        assert account["owner_id"] != owner
        assert web.password_matches(PASSWORD, account["password_hash"])
        after = [connection.execute("SELECT * FROM " + table).fetchall()
                 for table in ("openai_api_budget", "openai_api_calls", "video_ai_budget", "video_provider_calls")]
    assert after == before
    visitor.cookies.clear()
    assert visitor.post("/api/auth/login", json={"email": "NEW@example.test", "password": PASSWORD}).status_code == 200


@pytest.mark.parametrize("changes", [
    {"password_confirmation": PASSWORD + " different"}, {"password": "short"},
    {"email": "not-an-email"}, {"is_platform_owner": True}, {"owner_id": "portal_admin"},
])
def test_signup_rejects_invalid_fields_and_authority_injection(portal, changes):
    setup(portal)
    assert register(guest(portal), **changes).status_code == 400
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM portal_accounts").fetchone()["n"] == 1


def test_signup_rejects_cross_site_oversized_and_non_json_requests(portal):
    setup(portal)
    visitor = guest(portal)
    body = {"email": "new@example.test", "password": PASSWORD, "password_confirmation": PASSWORD}
    for bad in ("https://evil.example", "null", ""):
        assert visitor.post("/api/auth/register", json=body, headers={"Origin": bad}).status_code == 403
    assert visitor.post("/api/auth/register", json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert visitor.post("/api/auth/register", content="x" * 9000, headers={"Content-Type": "application/json"}).status_code == 413
    assert visitor.post("/api/auth/register", content="plain").status_code == 415


def test_signup_does_not_overwrite_email_or_authenticated_session(portal):
    setup(portal)
    original = portal.cookies.get(web.COOKIE)
    assert register(portal).status_code == 409
    assert portal.cookies.get(web.COOKIE) == original
    assert register(guest(portal), " OWNER@Example.Test ").status_code == 409
    assert portal.get("/api/session").json()["user"]["is_platform_owner"] is True


def test_pending_invitation_cannot_be_taken_by_public_signup(portal, monkeypatch):
    setup(portal)
    monkeypatch.setattr(portal_access, "MAX_PILOT_ACCOUNTS", 2)
    invitation = invite(portal, "invited@example.test")
    assert register(guest(portal), "invited@example.test").headers["x-narma-error"] == "PORTAL_INVITATION_PENDING"
    assert register(guest(portal), "other@example.test").headers["x-narma-error"] == "PORTAL_PILOT_FULL"
    assert accept(guest(portal), invitation, "invited@example.test").status_code == 201


def test_expired_invitation_does_not_block_signup(portal):
    setup(portal)
    invitation = invite(portal, "new@example.test")
    with database() as connection:
        connection.execute("UPDATE portal_invitations SET created_at=now()-interval '2 days',expires_at=now()-interval '1 day'")
    assert register(guest(portal)).status_code == 201
    assert accept(guest(portal), invitation, "new@example.test").status_code == 400


@pytest.mark.parametrize("same_email", [False, True])
def test_concurrent_signup_never_exceeds_capacity_or_duplicates_email(portal, monkeypatch, same_email):
    setup(portal)
    monkeypatch.setattr(portal_access, "MAX_PILOT_ACCOUNTS", 2)
    barrier = Barrier(2)
    def enter(index):
        barrier.wait(timeout=10)
        return register(guest(portal), f"new{0 if same_email else index}@example.test").status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(enter, range(2))) == [201, 409]
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM portal_accounts").fetchone()["n"] == 2
        assert connection.execute("SELECT count(*) AS n FROM portal_accounts WHERE is_platform_owner").fetchone()["n"] == 1


def test_signup_rate_limit_survives_client_and_email_rotation(portal):
    setup(portal)
    for index in range(5):
        assert register(guest(portal), f"new{index}@example.test").status_code == 201
    response = register(guest(portal), "sixth@example.test")
    assert response.status_code == 429
