from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from narma_video import player_program
from narma_video.db import database
from test_learning import client, positioned, plan, check
from test_hero_pool import browser, OWNER


@pytest.fixture
def program_client(client):
    player_program.attach_program(client.app)
    return client


def test_focus_is_owned_persistent_and_never_silently_replaces_stale_plan(program_client):
    c = program_client
    assert c.get('/api/program').json()['stage'] == 'upload'
    job = positioned(c)
    assert c.get('/api/program').json()['stage'] == 'choose'
    active = plan(c, job)
    data = c.get('/api/program').json()
    assert data['focus']['id'] == active['id'] and data['stage'] == 'practice'
    assert c.put(f"/api/program/focus/{active['id']}", json={}).status_code == 200
    assert c.put(f"/api/program/focus/{uuid4()}", json={}).status_code == 404
    assert c.put(f"/api/program/focus/{active['id']}", json={}, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert c.patch(f"/api/learning/plans/{active['id']}", json={'status': 'paused'}).status_code == 200
    data = c.get('/api/program').json()
    assert data['focus'] is None and data['focus_needs_review']
    assert c.put(f"/api/program/focus/{active['id']}", json={}).status_code == 409


def test_next_game_excludes_old_unknown_and_checked_games(program_client):
    c = program_client
    now = datetime.now(timezone.utc)
    baseline = positioned(c, played_at=now-timedelta(days=4))
    active = plan(c, baseline)
    with database() as con:
        con.execute("UPDATE learning_plans SET created_at=now()-interval '2 days' WHERE id=%s", (active['id'],))
    positioned(c, '8963624401', played_at=now-timedelta(days=3))
    positioned(c, '8963624402')
    new = positioned(c, '8963624403', played_at=now-timedelta(days=1))
    data = c.get('/api/program').json()
    assert data['stage'] == 'check'
    assert [r['job_id'] for r in data['check_candidates']] == [new]
    assert check(c, active, new).status_code == 200
    assert c.get('/api/program').json()['stage'] == 'practice'
