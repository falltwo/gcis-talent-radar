from test_api import c, account


def test_demo_disabled_by_default(c, monkeypatch):
    monkeypatch.delenv('RECRUITMENT_DEMO_ENABLED', raising=False)
    assert c.post('/auth/demo').status_code == 404


def test_demo_persists_and_isolates_company(c, monkeypatch):
    monkeypatch.setenv('RECRUITMENT_DEMO_ENABLED', '1')
    first=c.post('/auth/demo', headers={'Origin':'http://testserver'})
    assert first.status_code==200,first.text
    headers={'Authorization':'Bearer '+first.json()['access_token']}
    batch=c.post('/batches',headers=headers,json={'message':'十位工程師'}).json()
    second=c.post('/auth/demo').json()
    again={'Authorization':'Bearer '+second['access_token']}
    assert c.get('/batches/'+str(batch['id']),headers=again).status_code==200
    assert c.get('/auth/me',headers=again).json()['company_name']=='本機示範公司'
    other=account(c,'separate@example.com')
    assert c.get('/batches/'+str(batch['id']),headers=other).status_code==404
    assert c.get('/batches',headers=other).json()==[]
    assert c.post('/auth/demo',headers={'Origin':'https://untrusted.example'}).status_code==403
    assert c.post('/auth/demo',headers={'Host':'external.example'}).status_code==403
    assert c.post('/auth/register',json={'company_name':'冒用','name':'HR','email':'local-demo@recruitment.invalid','password':'strong-password-123'}).status_code==422


def test_mounted_demo_accepts_same_origin(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from recruitment.backend.integration import install_recruitment
    monkeypatch.setenv('RECRUITMENT_DATABASE_URL',f'sqlite:///{tmp_path / "demo.db"}')
    monkeypatch.setenv('RECRUITMENT_DEMO_ENABLED','1')
    monkeypatch.setenv('LLM_MODE','rules')
    parent=FastAPI();install_recruitment(parent)
    with TestClient(parent) as client:
        result=client.post('/api/recruitment/mvp/auth/demo',headers={'Origin':'http://testserver'})
        assert result.status_code==200,result.text
