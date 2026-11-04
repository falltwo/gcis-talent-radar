import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from recruitment.backend.main import create_app
from recruitment.backend.models import JobPosting
from recruitment.backend.parser import parse

@pytest.fixture
def c(monkeypatch):
    from pathlib import Path
    from uuid import uuid4
    tmp_path=Path(__file__).resolve().parents[2] / '.test-data' / ('test-' + uuid4().hex)
    tmp_path.mkdir(parents=True)
    monkeypatch.setenv('ALLOW_REGISTRATION','true')
    monkeypatch.setenv('LLM_MODE','rules')
    with TestClient(create_app(f'sqlite:///{tmp_path / "test.db"}'),raise_server_exceptions=False) as client: yield client

def account(c,email='hr@example.com'):
    assert c.post('/auth/register',json={'company_name':'測試公司','name':'HR','email':email,'password':'strong-password-123'}).status_code==201
    r=c.post('/auth/login',json={'email':email,'password':'strong-password-123'})
    assert r.status_code==200
    return {'Authorization':'Bearer '+r.json()['access_token']}

def template(c,h,title='經理',salary=50000):
    data={'title':title,'description':'工作內容','requirements':'相關經驗','location':'台北'}
    if salary: data.update(salary_min=salary,salary_max=salary)
    assert c.post('/job-templates',headers=h,json=data).status_code==201

def draft(c,h,text='兩個經理，經理月薪十萬元'):
    r=c.post('/batches',headers=h,json={'message':text})
    assert r.status_code==201,r.text
    return r.json()

def edit(c,h,b,i,**changes):
    data={k:i[k] for k in ['title','quantity','description','requirements','location','salary_min','salary_max','salary_type','currency']}
    data.update(changes)
    return c.put(f'/batches/{b["id"]}/items/{i["id"]}',headers=h,json=data)

def test_parser():
    rows=parse('我要找三個工程師、五個助理、一個除錯員、兩個經理，經理月薪十萬元。')
    assert [i['quantity'] for i in rows]==[3,5,1,2]
    assert rows[-1]['salary_min']==100000
    assert parse('2位工程師，工程師月薪40,000至60,000元')[0]['salary_max']==60000
    for text in ['找一些人','一個經理，月薪十萬','一個經理，經理薪水十萬','零個助理','一個經理，經理月薪十萬，經理月薪五萬']:
        with pytest.raises(ValueError): parse(text)

def test_full_flow(c):
    h=account(c)
    for t in ['工程師','助理','除錯員','經理']: template(c,h,t)
    b=draft(c,h,'三個工程師、五個助理、一個除錯員、兩個經理，經理月薪十萬元')
    assert len(b['items'])==4
    assert b['items'][-1]['salary_min']==100000
    assert b['items'][-1]['salary_source']=='hr_explicit'
    assert c.post(f'/batches/{b["id"]}/confirm',headers=h).status_code==422
    assert c.post(f'/batches/{b["id"]}/publish',headers=h).status_code==409
    for i in b['items']: assert edit(c,h,b,i,confirm_salary=True).status_code==200
    assert c.post(f'/batches/{b["id"]}/confirm',headers=h).status_code==200
    r=c.post(f'/batches/{b["id"]}/publish',headers=h)
    assert r.status_code==200,r.text
    assert len(r.json()['postings'])==4
    assert r.json()['postings'][-1]['salary_min']==100000
    assert c.post(f'/batches/{b["id"]}/publish',headers=h).status_code==409
    assert len(c.get('/job-postings',headers=h).json())==4
    assert len(c.get('/chat-logs',headers=h).json())==2

def test_reference_priority_missing(c):
    h=account(c)
    assert c.post('/salary-templates',headers=h,json={'job_title':'經理','salary_min':40000,'salary_max':60000,'data_source':'HR 提供的內部表，非市場統計'}).status_code==201
    b=draft(c,h,'一個經理、一個助理')
    assert b['items'][0]['salary_source']=='salary_reference'
    assert not b['items'][0]['salary_confirmed']
    assert b['items'][1]['salary_min'] is None
    template(c,h)
    assert draft(c,h,'一個經理')['items'][0]['salary_source']=='company_template'
    r=c.post('/chat',headers=h,json={'message':'助理薪資是多少？'})
    assert r.json()['salary_references']==[]
    assert '查無資料' in r.json()['message']
    assert len(c.post('/chat',headers=h,json={'message':'經理月薪？'}).json()['company_templates'])==1

def test_isolation_auth(c):
    a=account(c); b=account(c,'other@example.com'); template(c,a); d=draft(c,a)
    for p in ['/job-templates','/salary-templates','/job-postings','/chat-logs','/batches']: assert c.get(p,headers=b).json()==[]
    assert c.get(f'/batches/{d["id"]}',headers=b).status_code==404
    for action in ['confirm','publish']: assert c.post(f'/batches/{d["id"]}/{action}',headers=b).status_code==404
    assert edit(c,b,d,d['items'][0]).status_code==404
    assert c.get('/batches').status_code in [401,403]
    assert c.post('/auth/login',json={'email':'hr@example.com','password':'bad'}).status_code==401
    assert c.post('/auth/logout',headers=a).status_code==204
    assert c.get('/batches',headers=a).status_code==401

def test_edit_invalidates(c):
    h=account(c); template(c,h); b=draft(c,h)
    assert c.post(f'/batches/{b["id"]}/confirm',headers=h).status_code==200
    r=edit(c,h,b,b['items'][0],quantity=4)
    assert r.json()['status']=='draft'
    assert r.json()['items'][0]['salary_min']==100000
    assert c.post(f'/batches/{b["id"]}/publish',headers=h).status_code==409
    assert edit(c,h,b,b['items'][0],salary_max=1).status_code==422

def test_atomic_rollback(c):
    h=account(c); template(c,h); template(c,h,'工程師')
    b=draft(c,h,'一個經理、兩個工程師，經理月薪十萬元，工程師月薪六萬元')
    assert c.post(f'/batches/{b["id"]}/confirm',headers=h).status_code==200
    count=0
    def fail(mapper,connection,target):
        nonlocal count
        count+=1
        if count==2: raise RuntimeError('injected failure')
    event.listen(JobPosting,'before_insert',fail)
    try: assert c.post(f'/batches/{b["id"]}/publish',headers=h).status_code==500
    finally: event.remove(JobPosting,'before_insert',fail)
    assert c.get('/job-postings',headers=h).json()==[]
    assert c.get(f'/batches/{b["id"]}',headers=h).json()['status']=='confirmed'
    assert not any(x['action']=='publish_batch' for x in c.get('/audit-logs',headers=h).json())
    assert c.post(f'/batches/{b["id"]}/publish',headers=h).status_code==200

def test_expiry_and_registration_guard(c,monkeypatch):
    from sqlalchemy import select
    from datetime import datetime,timedelta,timezone
    from recruitment.backend.models import AccessToken
    h=account(c)
    with c.app.state.session_factory() as s:
        t=s.scalar(select(AccessToken)); t.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1); s.commit()
    assert c.get('/batches',headers=h).status_code==401
    monkeypatch.setenv('ALLOW_REGISTRATION','false')
    assert c.post('/auth/register',json={'company_name':'a','name':'b','email':'x@y.com','password':'long-password-123'}).status_code==403

def test_concurrent_publish(c):
    from concurrent.futures import ThreadPoolExecutor
    h=account(c); template(c,h); b=draft(c,h)
    assert c.post(f'/batches/{b["id"]}/confirm',headers=h).status_code==200
    def publish(_): return c.post(f'/batches/{b["id"]}/publish',headers=h).status_code
    with ThreadPoolExecutor(max_workers=2) as pool: statuses=list(pool.map(publish,range(2)))
    assert sorted(statuses)==[200,409]
    assert len(c.get('/job-postings',headers=h).json())==1
