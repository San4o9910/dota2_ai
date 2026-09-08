"""The public product works without access to accounts or model providers."""
import pytest
from fastapi.testclient import TestClient

from narma_video import api, web, explore


@pytest.fixture
def public_client(monkeypatch):
    monkeypatch.setenv('NARMA_EXPLORE_REFRESH_ENABLED', '0')
    monkeypatch.setenv('APP_ORIGIN', 'https://narma.example.test')

    def forbidden_database():
        raise AssertionError('Public browsing must not read account data')

    monkeypatch.setattr(api, 'database', forbidden_database)
    monkeypatch.setattr(web, 'database', forbidden_database)
    return TestClient(api.app, base_url='https://narma.example.test')


def test_public_browsing_does_not_require_database_or_login(public_client):
    for path in ('/', '/heroes', '/learn', '/practice', '/updates'):
        response = public_client.get(path)
        assert response.status_code == 200
        assert '/assets/explore.js' in response.text
        assert 'script-src \'self\'' in response.headers['content-security-policy']
        assert response.headers['x-frame-options'] == 'DENY'

    assert len(public_client.get('/api/explore/heroes').json()['heroes']) >= 100
    assert public_client.get('/api/explore/updates').json()['news']
    assert public_client.get('/api/explore/learning').json()['exercises']


def test_public_launch_does_not_expose_personal_reports_or_provider_access(public_client):
    for path in ('/api/profile', '/api/replays', '/api/hero-pool',
                 '/api/learning', '/api/integrations/chatgpt'):
        response = public_client.get(path)
        assert response.status_code == 401, path
        assert response.headers['cache-control'] == 'no-store'
    response = public_client.post('/api/integrations/chatgpt/connect', json={},
                                  headers={'Origin': 'https://foreign.example'})
    assert response.status_code in (401, 403)


def test_private_navigation_direct_links_keep_the_portal_shell(public_client):
    for path in ('/replays', '/hero-pool', '/player', '/my-learning', '/account', '/setup'):
        response = public_client.get(path)
        assert response.status_code == 200
        assert '/assets/portal.js' in response.text
        assert response.headers['cache-control'] == 'no-store'
