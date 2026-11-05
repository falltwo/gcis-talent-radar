"""Portal records survive a process restart without crossing browser sessions."""
import json
import time
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.main import app
import api.mock104 as portal
from api.mock104_store import PersistentPortalSessions, RETENTION_SECONDS
from tests.test_mock104 import create


@pytest.fixture
def root():
    path = Path('.test-data') / ('portal-store-' + uuid.uuid4().hex)
    path.mkdir(parents=True)
    return path


def test_submission_and_review_survive_restart(monkeypatch, root):
    registry = PersistentPortalSessions(root)
    monkeypatch.setattr(portal, 'sessions', registry)
    with TestClient(app) as client:
        response = client.post('/api/mock104/start', json={})
        assert 'Max-Age=2592000' in response.headers['set-cookie']
        identifier = create(client)
        assert client.post(f'/api/mock104/jobs/{identifier}/submit', json={}).status_code == 200
        monkeypatch.setattr(portal, 'sessions', PersistentPortalSessions(root))
        restored = client.post('/api/mock104/start', json={}).json()['jobs']
        assert len(restored) == 1 and restored[0]['id'] == identifier
        assert restored[0]['status'] == 'PENDING_APPROVAL'
        with TestClient(app) as stranger:
            assert stranger.get('/api/mock104/state').status_code == 204
            assert stranger.post('/api/mock104/start', json={}).json()['jobs'] == []
            assert stranger.post(f'/api/mock104/jobs/{identifier}/approve', json={}).status_code == 404
        for action in ('approve', 'complete'):
            assert client.post(f'/api/mock104/jobs/{identifier}/{action}', json={}).status_code == 200
        monkeypatch.setattr(portal, 'sessions', PersistentPortalSessions(root))
        assert client.get('/api/mock104/state').json()['jobs'][0]['status'] == 'SUCCEEDED'


def test_refresh_extends_session_and_expiry_preserves_database(root):
    registry = PersistentPortalSessions(root)
    key = registry.start_empty()
    folder = registry.folder(key)
    registry.sessions[key]['expires_at'] = time.time() + 60
    registry.refresh(key)
    assert registry.sessions[key]['expires_at'] > time.time() + RETENTION_SECONDS - 5
    registry.metadata(folder, time.time() - 1)
    restarted = PersistentPortalSessions(root)
    with pytest.raises(HTTPException) as error:
        with restarted.session(key):
            pass
    assert error.value.status_code == 404
    assert (folder / 'jobs.sqlite3').is_file()
    assert json.loads((folder / 'session.json').read_text())['expires_at'] < time.time()


@pytest.mark.parametrize('key', [None, '../other', 'a' * 100])
def test_invalid_cookie_cannot_select_a_store(root, key):
    with pytest.raises(HTTPException):
        with PersistentPortalSessions(root).session(key):
            pass
