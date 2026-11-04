"""Verify same-server mounting, lifespan and separate recruitment database."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recruitment.backend.integration import install_recruitment


def test_mounted_service_starts_and_preserves_parent_lifespan(tmp_path, monkeypatch):
    monkeypatch.setenv('RECRUITMENT_DATABASE_URL', f'sqlite:///{tmp_path / "recruitment.db"}')
    monkeypatch.setenv('LLM_MODE', 'rules')
    monkeypatch.setenv('ALLOW_REGISTRATION', 'true')
    events=[]
    @asynccontextmanager
    async def parent_lifespan(app):
        events.append('parent_start')
        yield {'parent_state':True}
        events.append('parent_stop')
    parent=FastAPI(lifespan=parent_lifespan)
    child=install_recruitment(parent)
    assert not (tmp_path/'recruitment.db').exists()
    with TestClient(parent) as client:
        assert events==['parent_start']
        assert (tmp_path/'recruitment.db').exists()
        assert client.get('/api/recruitment/mvp/health').json()['parser']=='rules'
        assert client.get('/api/recruitment/mvp/docs').status_code==200
        assert '/batches' in client.get('/api/recruitment/mvp/openapi.json').json()['paths']
        assert client.get('/api/recruitment/mvp/batches').status_code in [401,403]
        response=client.post('/api/recruitment/mvp/auth/register',json={'company_name':'隔離測試','name':'HR','email':'mounted@example.com','password':'mounted-password-123'})
        assert response.status_code==201,response.text
    assert events==['parent_start','parent_stop']
    assert str(child.state.engine.url).endswith('recruitment.db')


def test_existing_radar_app_mounts_recruitment():
    from api.main import app
    mounts=[r for r in app.routes if getattr(r,'path',None)=='/api/recruitment/mvp']
    assert len(mounts)==1
    assert mounts[0].app is app.state.recruitment
    assert any(getattr(r,'path',None)=='/api/recruitment/platforms' for r in app.routes)
    assert any(getattr(r,'path',None)=='/api/mock104/start' for r in app.routes)
    assert any(getattr(r,'path',None)=='/recruitment-agent' for r in app.routes)
    assert any(getattr(r,'path',None)=='/' for r in app.routes)
    assert any(getattr(r,'path',None)=='/api/reports/{report_id}' for r in app.routes)
