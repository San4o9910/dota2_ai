"""Synthetic OAuth fixtures only. No account login or model inference."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from threading import Event
from uuid import uuid4

from cryptography.fernet import Fernet
import pytest

from narma_video import chatgpt_auth as auth
from narma_video.db import database
from narma_video.web import COOKIE
from test_hero_pool import browser, OWNER


def jwt(seconds=3600, account="synthetic-chatgpt-account"):
    payload = {"exp": auth._now().timestamp() + seconds,
               "https://api.openai.com/auth": {"chatgpt_account_id": account}}
    return "synthetic." + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=") + ".unsigned"


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("NARMA_CHATGPT_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("NARMA_CHATGPT_OWNER_ID", raising=False)


@pytest.fixture
def client(browser, key):
    with database() as connection:
        connection.execute("DELETE FROM portal_auth_limits WHERE bucket=%s", ("chatgpt-connect:" + OWNER,))
    auth.attach_chatgpt(browser.app)
    return browser


@pytest.fixture
def oauth(monkeypatch):
    calls = []
    def post(url, *, json_body=None, form=None):
        calls.append((url, json_body, form))
        if url == auth.USERCODE_URL:
            return 200, {"device_auth_id": "synthetic-private-device", "user_code": "ABCD-1234", "interval": "3",
                         "verification_uri": "https://attacker.invalid/ignored"}
        if url == auth.DEVICE_TOKEN_URL:
            return 200, {"authorization_code": "synthetic-private-code", "code_verifier": "synthetic-private-verifier"}
        return 200, {"access_token": jwt(), "refresh_token": "synthetic-private-refresh"}
    monkeypatch.setattr(auth, "_oauth_post", post)
    return calls


URL = "/api/integrations/chatgpt"


def due():
    with database() as connection:
        connection.execute("UPDATE chatgpt_connections SET next_poll_at=now()-interval '1 second' WHERE owner_id=%s", (OWNER,))


def login(client):
    response = client.post(URL + "/connect", json={})
    assert response.status_code == 200, response.text
    started = response.json()
    due()
    response = client.post(URL + "/poll", json={"auth_generation": started["auth_generation"]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "connected"
    return response.json()


def seed_connected(seconds=3600):
    generation = uuid4()
    payload = {"access_token": jwt(seconds), "refresh_token": "old-synthetic-refresh",
               "access_expires_at": auth._now().timestamp() + seconds, "account_id": "synthetic-chatgpt-account"}
    with database() as connection:
        connection.execute("""INSERT INTO chatgpt_connections
            (owner_id,generation,state,secret_ciphertext,connected_at)
            VALUES (%s,%s,'connected',%s,now()) ON CONFLICT(owner_id) DO UPDATE SET
            generation=excluded.generation,state='connected',secret_ciphertext=excluded.secret_ciphertext,
            expires_at=NULL,next_poll_at=NULL,quota_paused=false,paused_until=NULL""",
            (OWNER, generation, auth._seal(OWNER, generation, payload)))
    return str(generation)


def test_encryption_binds_owner_and_generation_and_rejects_tampering(key):
    generation = uuid4()
    secret = {"access_token": "synthetic-secret", "refresh_token": "synthetic-refresh"}
    sealed = auth._seal(OWNER, generation, secret)
    assert "synthetic" not in sealed
    row = {"owner_id": OWNER, "generation": generation, "secret_ciphertext": sealed}
    assert auth._open(row) == secret
    for changed in ({**row, "owner_id": "other"}, {**row, "generation": uuid4()},
                    {**row, "secret_ciphertext": sealed[:-6] + "AAAAAA"}):
        with pytest.raises(auth.AuthError, match="CHATGPT_AUTH_DECRYPT"):
            auth._open(changed)


def test_missing_invalid_encryption_key_is_not_configured(monkeypatch):
    for key in ("", "invalid", "не ключ"):
        monkeypatch.setenv("NARMA_CHATGPT_ENCRYPTION_KEY", key)
        assert not auth.configured()
        with pytest.raises(auth.AuthError, match="CHATGPT_NOT_CONFIGURED"):
            auth._fernet()


def test_token_normalization_bounds_and_rotation(key):
    normalized = auth._tokens({"access_token": jwt(), "refresh_token": "new-refresh"})
    assert normalized["account_id"] == "synthetic-chatgpt-account"
    assert auth._tokens({"access_token": jwt()}, old=normalized)["refresh_token"] == "new-refresh"
    for body in ({"access_token": jwt(-100), "refresh_token": "refresh"},
                 {"access_token": "bad\nheader", "refresh_token": "refresh"},
                 {"access_token": jwt(), "refresh_token": ""}):
        with pytest.raises(auth.AuthError, match="CHATGPT_AUTH_RESPONSE"):
            auth._tokens(body)


def test_http_requires_cookie_csrf_and_bounded_empty_body(client, oauth):
    client.cookies.clear()
    assert client.get(URL).status_code == 401
    client.cookies.set(COOKIE, "P" * 43)
    assert client.post(URL + "/connect", json={}, headers={"Origin": "https://attacker.invalid"}).status_code == 403
    assert client.post(URL + "/connect", json={"owner_id": "other"}).status_code == 400
    assert client.post(URL + "/connect", content="x" * (auth.MAX_BODY + 1), headers={"Content-Type": "application/json"}).status_code == 413
    assert client.post(URL + "/connect", content="{}").status_code == 415
    assert client.post(URL + "/poll", json={"auth_generation": "invalid"}).status_code == 400
    assert not oauth


def test_connect_is_idempotent_bounded_and_hides_provider_secrets(client, oauth):
    assert client.get(URL).json()["status"] == "disconnected"
    first = client.post(URL + "/connect", json={}).json()
    second = client.post(URL + "/connect", json={}).json()
    assert first["auth_generation"] == second["auth_generation"] and len(oauth) == 1
    assert first["pending"]["verification_url"] == auth.VERIFICATION_URL
    assert first["pending"]["poll_interval_seconds"] == 3
    assert first["pending"]["user_code"] == "ABCD-1234"
    serialized = json.dumps(first)
    assert "synthetic-private" not in serialized and "access_token" not in serialized
    response = client.post(URL + "/poll", json={"auth_generation": first["auth_generation"]})
    assert response.json()["status"] == "pending" and len(oauth) == 1
    with database() as connection:
        row = connection.execute("SELECT * FROM chatgpt_connections WHERE owner_id=%s", (OWNER,)).fetchone()
        assert "synthetic-private" not in row["secret_ciphertext"]
        assert auth._open(row)["device_auth_id"] == "synthetic-private-device"


def test_successful_exchange_is_owner_scoped_and_only_internal_credentials(client, oauth):
    connected = login(client)
    assert connected["pending"] is None and connected["available"] is True
    assert len(oauth) == 3
    credential = auth.get_access_credentials(OWNER)
    assert credential["generation"] == connected["auth_generation"]
    assert credential["account_id"] == "synthetic-chatgpt-account"
    assert auth.credentials_current(OWNER, connected["auth_generation"])
    with pytest.raises(auth.AuthError, match="CHATGPT_OWNER_ONLY"):
        auth.get_access_credentials("other-owner")
    with database() as connection:
        assert auth.current_connection(connection, "other-owner") is None
    assert "synthetic-private" not in client.get(URL).text
    assert "access_token" not in client.get(URL).text


def test_cancel_then_late_poll_cannot_reconnect(client, oauth):
    first = client.post(URL + "/connect", json={}).json()
    disconnected = client.request("DELETE", URL, json={}).json()
    assert disconnected["status"] == "disconnected"
    assert disconnected["auth_generation"] != first["auth_generation"]
    assert client.post(URL + "/poll", json={"auth_generation": first["auth_generation"]}).json()["status"] == "disconnected"
    assert len(oauth) == 1
    assert not auth.enabled(OWNER)
    with database() as connection:
        assert connection.execute("SELECT secret_ciphertext FROM chatgpt_connections").fetchone()["secret_ciphertext"] is None


def test_expired_grant_never_polls_provider(client, oauth):
    first = client.post(URL + "/connect", json={}).json()
    with database() as connection:
        connection.execute("UPDATE chatgpt_connections SET expires_at=now()-interval '1 second'")
    assert client.get(URL).json()["status"] == "expired"
    result = client.post(URL + "/poll", json={"auth_generation": first["auth_generation"]}).json()
    assert result["status"] == "expired" and len(oauth) == 1
    with database() as connection:
        assert connection.execute("SELECT secret_ciphertext FROM chatgpt_connections").fetchone()["secret_ciphertext"] is None


def test_pending_responses_follow_poll_interval(client, oauth, monkeypatch):
    started = client.post(URL + "/connect", json={}).json()
    calls = []
    def waiting(url, **kwargs):
        calls.append(url)
        return 403, {"sensitive_detail": "never publish this"}
    monkeypatch.setattr(auth, "_oauth_post", waiting)
    due()
    for _ in range(3):
        result = client.post(URL + "/poll", json={"auth_generation": started["auth_generation"]})
        assert result.json()["status"] == "pending"
        assert "sensitive_detail" not in result.text
    assert calls == [auth.DEVICE_TOKEN_URL]


@pytest.mark.parametrize("failure", ["timeout", "malformed", "rejected"])
def test_uncertain_exchange_requires_new_grant(client, oauth, monkeypatch, failure):
    started = client.post(URL + "/connect", json={}).json()
    calls = []
    def exchange(url, **kwargs):
        calls.append(url)
        if url == auth.DEVICE_TOKEN_URL:
            return 200, {"authorization_code": "one-use", "code_verifier": "verifier"}
        if failure == "timeout":
            raise auth.AuthError("CHATGPT_AUTH_UNAVAILABLE")
        if failure == "malformed":
            return 200, {"access_token": "only-access-no-refresh"}
        return 400, {"error": "one-use token rejected, sensitive details"}
    monkeypatch.setattr(auth, "_oauth_post", exchange)
    due()
    first = client.post(URL + "/poll", json={"auth_generation": started["auth_generation"]})
    assert first.json()["status"] == "reconnect_required"
    assert client.post(URL + "/poll", json={"auth_generation": started["auth_generation"]}).json()["status"] == "reconnect_required"
    assert calls == [auth.DEVICE_TOKEN_URL, auth.TOKEN_URL]


def test_refresh_rotates_once_and_remains_internal(client, oauth):
    generation = seed_connected(seconds=10)
    first = auth.get_access_credentials(OWNER)
    second = auth.get_access_credentials(OWNER)
    assert first == second and first["generation"] == generation
    assert len(oauth) == 1 and oauth[0][2]["refresh_token"] == "old-synthetic-refresh"
    with database() as connection:
        secret = auth._open(connection.execute("SELECT * FROM chatgpt_connections").fetchone())
        assert secret["refresh_token"] == "synthetic-private-refresh"


@pytest.mark.parametrize("failure", ["timeout", "rejected", "malformed"])
def test_uncertain_refresh_clears_session_and_never_retries(client, monkeypatch, failure):
    original = seed_connected(seconds=10)
    calls = []
    def fail(url, **kwargs):
        calls.append(url)
        if failure == "timeout":
            raise auth.AuthError("CHATGPT_AUTH_UNAVAILABLE")
        if failure == "malformed":
            return 200, {"bad": "response"}
        return 401, {"error": "revoked token"}
    monkeypatch.setattr(auth, "_oauth_post", fail)
    with pytest.raises(auth.AuthError, match="CHATGPT_AUTH_EXPIRED"):
        auth.get_access_credentials(OWNER)
    with pytest.raises(auth.AuthError, match="CHATGPT_NOT_CONNECTED"):
        auth.get_access_credentials(OWNER)
    assert len(calls) == 1
    assert not auth.credentials_current(OWNER, original)
    assert client.get(URL).json()["status"] == "reconnect_required"


def test_refresh_429_cooldown_is_not_relogin_or_busy_retry(client, monkeypatch):
    generation = seed_connected(seconds=10)
    calls = []
    def limited(url, **kwargs):
        calls.append(url)
        return 429, {"error": "rate limited"}
    monkeypatch.setattr(auth, "_oauth_post", limited)
    for _ in range(2):
        with pytest.raises(auth.AuthError, match="CHATGPT_AUTH_RATE_LIMIT"):
            auth.get_access_credentials(OWNER)
    assert len(calls) == 1 and auth.credentials_current(OWNER, generation)
    assert client.get(URL).json()["status"] == "connected"


def test_quota_unknown_stays_paused_and_old_results_cannot_affect_new_login(client, oauth):
    original = seed_connected()
    auth.record_provider_pause(OWNER, original, seconds=None)
    assert not auth.enabled(OWNER)
    view = client.get(URL).json()
    assert view["quota_paused"] and view["paused_until"] is None
    assert auth.credentials_current(OWNER, original)  # In-flight validated result can still settle.
    with pytest.raises(auth.AuthError, match="CHATGPT_QUOTA"):
        auth.get_access_credentials(OWNER)
    client.request("DELETE", URL, json={})
    newer = seed_connected()
    auth.record_provider_pause(OWNER, original, seconds=None)
    auth.mark_reconnect_required(OWNER, original)
    assert auth.enabled(OWNER) and auth.credentials_current(OWNER, newer)


def test_known_quota_reset_resume_requires_time_to_pass(client):
    generation = seed_connected()
    auth.record_provider_pause(OWNER, generation, seconds=180)
    assert not auth.enabled(OWNER)
    with database() as connection:
        connection.execute("UPDATE chatgpt_connections SET paused_until=now()-interval '1 second'")
    assert auth.enabled(OWNER)


def test_explicit_designated_owner_additionally_restricts_access(client, monkeypatch, oauth):
    monkeypatch.setenv("NARMA_CHATGPT_OWNER_ID", "different-owner")
    assert client.get(URL).status_code == 403
    assert client.post(URL + "/connect", json={}).status_code == 403
    assert not oauth


def test_provider_errors_never_print_tokens_or_response_body(client, monkeypatch, capsys):
    def rejected(url, **kwargs):
        return 403, {"error": "synthetic-secret-provider-response"}
    monkeypatch.setattr(auth, "_oauth_post", rejected)
    result = client.post(URL + "/connect", json={})
    assert result.status_code == 401
    assert result.headers["X-Narma-Error"] == "CHATGPT_AUTH_REJECTED"
    assert "synthetic-secret" not in result.text + capsys.readouterr().out
    assert client.get(URL).json()["status"] == "disconnected"


def test_connect_rate_limit_is_durable_even_when_provider_fails(client, monkeypatch):
    calls = []
    def rejected(url, **kwargs):
        calls.append(url)
        return 503, {}
    monkeypatch.setattr(auth, "_oauth_post", rejected)
    for _ in range(5):
        assert client.post(URL + "/connect", json={}).status_code == 503
    assert client.post(URL + "/connect", json={}).status_code == 429
    assert len(calls) == 5


def test_status_does_not_mutate_or_contact_provider(client, oauth, monkeypatch):
    seed_connected()
    with database() as connection:
        before = connection.execute("SELECT * FROM chatgpt_connections").fetchone()
    assert client.get(URL).json()["status"] == "connected"
    assert auth.enabled(OWNER)
    assert not oauth
    with database() as connection:
        after = connection.execute("SELECT * FROM chatgpt_connections").fetchone()
    assert before == after


class SimulatedProcessCrash(BaseException):
    pass


@pytest.mark.parametrize("kind", ["exchange", "refresh"])
def test_process_crash_after_durable_intent_never_replays_one_use_grant(client, oauth, monkeypatch, kind):
    if kind == "exchange":
        generation = client.post(URL + "/connect", json={}).json()["auth_generation"]
        due()
    else:
        generation = seed_connected(seconds=10)
    calls = []
    def crash(url, **kwargs):
        calls.append(url)
        if url == auth.DEVICE_TOKEN_URL:
            return 200, {"authorization_code": "one-use", "code_verifier": "verifier"}
        raise SimulatedProcessCrash()
    monkeypatch.setattr(auth, "_oauth_post", crash)
    with pytest.raises(SimulatedProcessCrash):
        if kind == "exchange":
            auth.poll_connection(OWNER, generation)
        else:
            auth.get_access_credentials(OWNER)
    with database() as connection:
        row = connection.execute("SELECT * FROM chatgpt_connections").fetchone()
        assert row["rotation_kind"] == kind and row["rotation_started_at"] is not None
    count = len(calls)
    if kind == "exchange":
        assert auth.poll_connection(OWNER, generation)["status"] == "reconnect_required"
    else:
        with pytest.raises(auth.AuthError, match="CHATGPT_AUTH_EXPIRED"):
            auth.get_access_credentials(OWNER)
    assert len(calls) == count
    assert auth.connection_status(OWNER)["status"] == "reconnect_required"


def test_outbound_auth_url_is_exact_allowlist():
    for url in ("https://attacker.invalid/oauth/token", "http://auth.openai.com/oauth/token",
                "https://auth.openai.com@attacker.invalid/oauth/token", auth.TOKEN_URL + "?redirect=x"):
        with pytest.raises(auth.AuthError, match="CHATGPT_AUTH_REJECTED"):
            auth._oauth_post(url, form={})


@pytest.mark.skipif(os.environ.get("NARMA_SYNTHETIC_PGLITE") == "1", reason="Requires native PostgreSQL session locks")
def test_concurrent_refresh_uses_single_rotating_grant(client, monkeypatch):
    seed_connected(seconds=10)
    entered, release = Event(), Event()
    calls = []
    def refresh(url, **kwargs):
        calls.append(url)
        entered.set()
        assert release.wait(10)
        return 200, {"access_token": jwt(), "refresh_token": "new-rotated-refresh"}
    monkeypatch.setattr(auth, "_oauth_post", refresh)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(auth.get_access_credentials, OWNER)
        assert entered.wait(10)
        second = workers.submit(auth.get_access_credentials, OWNER)
        release.set()
        assert first.result(timeout=10) == second.result(timeout=10)
    assert len(calls) == 1


@pytest.mark.skipif(os.environ.get("NARMA_SYNTHETIC_PGLITE") == "1", reason="Requires native PostgreSQL session locks")
def test_disconnect_waiting_on_exchange_wins_over_late_success(client, oauth, monkeypatch):
    generation = client.post(URL + "/connect", json={}).json()["auth_generation"]
    due()
    entered, release = Event(), Event()
    def exchange(url, **kwargs):
        if url == auth.DEVICE_TOKEN_URL:
            return 200, {"authorization_code": "one-use", "code_verifier": "verifier"}
        entered.set()
        assert release.wait(10)
        return 200, {"access_token": jwt(), "refresh_token": "new-rotated-refresh"}
    monkeypatch.setattr(auth, "_oauth_post", exchange)
    with ThreadPoolExecutor(max_workers=2) as workers:
        polling = workers.submit(auth.poll_connection, OWNER, generation)
        assert entered.wait(10)
        cancelling = workers.submit(auth.disconnect, OWNER)
        release.set()
        assert polling.result(timeout=10)["status"] == "connected"
        assert cancelling.result(timeout=10)["status"] == "disconnected"
    assert auth.connection_status(OWNER)["status"] == "disconnected"
    assert auth.poll_connection(OWNER, generation)["status"] == "disconnected"
