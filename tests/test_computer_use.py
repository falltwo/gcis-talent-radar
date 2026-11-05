from types import SimpleNamespace
from contextlib import nullcontext
import sys

import pytest
from fastapi import HTTPException

from recruitment.computer_use import allowed_text,execute_actions,local_origin
from tests.test_mock104 import client,create


def test_worker_only_accepts_local_mock_origin():
    assert local_origin('http://127.0.0.1:8890')=='http://127.0.0.1:8890'
    with pytest.raises(HTTPException): local_origin('https://www.104.com.tw')


def test_only_approved_text_and_bounded_mouse_keyboard_actions(monkeypatch):
    monkeypatch.setattr('recruitment.computer_use.time.sleep',lambda _:None)
    events=[]
    page=SimpleNamespace(mouse=SimpleNamespace(click=lambda x,y:events.append(('click',x,y)),wheel=lambda x,y:events.append(('scroll',y))),keyboard=SimpleNamespace(insert_text=lambda t:events.append(('type',t)),press=lambda k:events.append(('key',k))))
    job={'title':'會計','headcount':3}
    execute_actions(page,[{'type':'click','x':100,'y':200},{'type':'type','text':'會計'},{'type':'key','key':'Tab'}],job)
    assert events[1]==('type','會計')
    for action in [{'type':'click','x':2000,'y':100},{'type':'key','key':'Control+L'},{'type':'type','text':'unapproved secret'},{'type':'evaluate','code':'fetch()'}]:
        with pytest.raises(ValueError): execute_actions(page,[action],job)
    with pytest.raises(RuntimeError): execute_actions(page,[{'type':'click','x':1,'y':1}],job,lambda:True)
    assert allowed_text('月薪面議',job)


def test_real_frame_hook_runs_after_each_completed_action(monkeypatch):
    monkeypatch.setattr('recruitment.computer_use.time.sleep',lambda _:None)
    events=[]
    page=SimpleNamespace(mouse=SimpleNamespace(click=lambda x,y:events.append('click')),keyboard=SimpleNamespace(insert_text=lambda t:events.append('type')))
    execute_actions(page,[{'type':'click','x':10,'y':10},{'type':'type','text':'會計'}],{'title':'會計'},on_action=lambda action:events.append('frame:'+action['type']))
    assert events==['click','frame:click','type','frame:type']


@pytest.mark.parametrize('amounts',[(50000,50000),(40000,60000)])
def test_salary_action_replaces_both_amounts_exactly_without_spinner_keys(monkeypatch,amounts):
    monkeypatch.setattr('recruitment.computer_use.time.sleep',lambda _:None)
    events=[]
    page=SimpleNamespace(keyboard=SimpleNamespace(press=lambda key:events.append(('key',key)),insert_text=lambda text:events.append(('text',text))))
    approved={'salary_mode':'RANGE','salary_min':amounts[0],'salary_max':amounts[1]}
    execute_actions(page,[{'type':'fill_salary','field':'salary_min','text':'49999'},{'type':'fill_salary','field':'salary_max'}],approved)
    assert events==[('key','Control+A'),('text',str(amounts[0])),('key','Tab'),('key','Control+A'),('text',str(amounts[1])),('key','Tab')]
    for change in [{'salary_mode':'NEGOTIABLE'},{'salary_min':None},{'salary_min':50000.0}]:
        with pytest.raises(ValueError):execute_actions(page,[{'type':'fill_salary','field':'salary_min'}],{**approved,**change})
    with pytest.raises(ValueError):execute_actions(page,[{'type':'fill_salary','field':'headcount'}],approved)


def test_external_verifier_reads_saved_normal_webpage_data(client):
    import api.mock104 as portal
    from recruitment.computer_use import saved_job
    identifier=create(client,salary_mode='NEGOTIABLE',salary_min=None,salary_max=None)
    service=next(iter(portal.sessions.sessions.values()))['service']
    actual=saved_job(service,identifier)
    assert actual['salary_mode']=='NEGOTIABLE'
    assert actual['salary_min'] is None and actual['salary_max'] is None
    assert actual['company_name']=='虛構示範企業'


def test_fill_only_verifies_saved_form_and_blocks_publication(client,monkeypatch):
    import api.mock104 as portal
    import recruitment.computer_use as worker
    from tests.test_mock104 import job
    approved=job(work_hours='08:00–17:00',schedule_system='固定班制',company_intro='本機測試')
    r=client.post('/api/mock104/agent/approve',json={'job':approved,'hr_confirmed':True,'fill_only':True})
    assert r.status_code==200,r.text
    run=r.json();cookie=client.cookies.get(portal.COOKIE)
    handlers={}
    def state():
        with portal.sessions.session(cookie) as session:return session['agent_run']
    def open_page(*args,**kwargs):
        assert client.post('/api/mock104/jobs',json=approved).status_code==201
    page=SimpleNamespace(route=lambda pattern,handler:handlers.update(route=handler),on=lambda *a:None,goto=open_page,
                         is_closed=lambda:state()['phase']=='FILLED',screenshot=lambda **kw:b'test-jpeg')
    context=SimpleNamespace(add_cookies=lambda *a:None,new_page=lambda:page)
    browser=SimpleNamespace(new_context=lambda **kw:context,close=lambda:None)
    chromium=SimpleNamespace(launch=lambda **kw:browser)
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=lambda:nullcontext(SimpleNamespace(chromium=chromium))))
    monkeypatch.setattr(worker,'decide',lambda *a:pytest.fail('Verified filled form must not trigger another decision'))
    worker.operate(portal.sessions,cookie,'http://127.0.0.1:8891',run['run_id'])
    assert state()['phase']=='FILLED'
    assert client.get('/api/mock104/state').json()['jobs'][0]['status']=='DRAFT'
    events=[]
    route=SimpleNamespace(request=SimpleNamespace(url='http://127.0.0.1:8891/api/mock104/jobs/x/submit',method='POST'),abort=lambda:events.append('blocked'),continue_=lambda:events.append('allowed'))
    handlers['route'](route)
    assert events==['blocked']


@pytest.mark.parametrize(('failure_at','error','code'),[
    ('launch',OSError('Chrome unavailable'),'BROWSER_START_FAILED'),
    ('goto',TimeoutError('Navigation timed out'),'BROWSER_TIMEOUT'),
    ('goto',OSError('Connection refused'),'BROWSER_NAVIGATION_FAILED'),
])
def test_worker_records_actual_failure_and_releases_slot(monkeypatch,caplog,failure_at,error,code):
    import recruitment.computer_use as worker
    def fail(*a,**kw): raise error
    page=SimpleNamespace(route=lambda *a:None,on=lambda *a:None,goto=fail)
    context=SimpleNamespace(add_cookies=lambda *a:None,new_page=lambda:page)
    browser=SimpleNamespace(new_context=lambda **kw:context)
    chromium=SimpleNamespace(launch=fail if failure_at=='launch' else lambda **kw:browser)
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=lambda:nullcontext(SimpleNamespace(chromium=chromium))))
    run={'run_id':'failure-test','phase':'READY'}
    session={'agent_run':run,'service':SimpleNamespace(listing=lambda *a:{'items':[]})}
    registry=SimpleNamespace(session=lambda _:nullcontext(session))
    cookie='failure-test-cookie'
    worker.active.add(cookie)
    worker.operate(registry,cookie,'http://127.0.0.1:8890','failure-test')
    assert run['phase']=='FAILED' and run['error_code']==code
    assert cookie not in worker.active
    assert 'Computer Use worker failed during' in caplog.text
    if failure_at!='launch': assert '已安裝' not in run['message']


@pytest.mark.parametrize('content',['not JSON','[]','{"note":"操作網站"}','{"actions":null}'])
def test_malformed_model_response_reports_model_error(monkeypatch,content):
    import recruitment.computer_use as worker
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only')
    monkeypatch.setattr(worker.requests,'post',lambda *a,**kw:SimpleNamespace(ok=True,json=lambda:{'choices':[{'message':{'content':content}}]}))
    with pytest.raises(RuntimeError,match='模型回傳的操作格式不完整'):
        worker.decide(b'screenshot',{'title':'會計'},'fill','')


def test_truncated_decision_retries_before_any_action(monkeypatch):
    import recruitment.computer_use as worker
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only')
    calls=[]
    def post(*args,**kwargs):
        calls.append(kwargs['json'])
        choice={'finish_reason':'length','message':{'content':'{"actions":['}} if len(calls)==1 else {'finish_reason':'stop','message':{'content':'{"note":"填寫","actions":[{"type":"click","x":10,"y":10}]}'}}
        return SimpleNamespace(ok=True,json=lambda:{'choices':[choice]})
    monkeypatch.setattr(worker.requests,'post',post)
    assert worker.decide(b'screenshot',{'title':'會計'},'fill','')['actions'][0]['type']=='click'
    assert len(calls)==2 and calls[0]['max_completion_tokens']==4000

def test_skill_action_replaces_exact_list_and_clears_empty_training(monkeypatch):
    import recruitment.computer_use as worker
    monkeypatch.setattr(worker.time,'sleep',lambda _:None)
    events=[]
    page=SimpleNamespace(keyboard=SimpleNamespace(press=lambda k:events.append(('key',k)),insert_text=lambda t:events.append(('text',t))))
    job={'required_skills':['html、css','需求分析，跨部門協作'],'trainable_skills':[]}
    worker.execute_actions(page,[{'type':'fill_skills','field':'required_skills'},{'type':'fill_skills','field':'trainable_skills'}],job)
    assert events==[('key','Control+A'),('text','html、css\n需求分析，跨部門協作\n'),('key','Control+A'),('text','')]
    with pytest.raises(ValueError):worker.execute_actions(page,[{'type':'fill_skills','field':'description'}],job)


def test_memory_keeps_verified_fields_separate_from_attempts_and_bounds_history():
    from recruitment.computer_use import ProgressMemory
    memory=ProgressMemory()
    for n in range(40):memory.action({'type':'type','text':str(n)})
    memory.verify({'title':'全端工程師','required_skills':['html','css']},{'title':'全端工程師','required_skills':['html、css']})
    assert memory.verified==['title']
    assert list(memory.differences)==['required_skills']
    assert len(memory.recent)==24
    assert memory.recent[0]['text']=='16'
    memory.verify({'title':'全端工程師','required_skills':['html、css']},{'title':'全端工程師','required_skills':['html、css']})
    assert memory.differences=={}
    assert 'current_url' in memory.context('http://127.0.0.1:8088/mock104')


def test_website_defaults_cannot_replace_prepared_employer_conditions():
    from recruitment.computer_use import required_field_differences
    from tests.test_mock104 import job
    approved=job(salary_min=40000,salary_max=40000,headcount=10,description='使用者指定的工作內容。')
    submitted={**approved,'salary_min':35000,'salary_max':45000,'description':'網站範本內容'}
    differences=required_field_differences(submitted,approved)
    assert set(differences)=={'salary_min','salary_max','description'}
    assert differences['salary_min']['required']==40000
    assert required_field_differences(approved,approved)=={}
    negotiable={**approved,'salary_mode':'NEGOTIABLE','salary_min':None,'salary_max':None}
    assert set(required_field_differences(approved,negotiable))=={'salary_mode','salary_min','salary_max'}

def test_first_saved_mismatch_hands_to_human_without_another_model_call(client,monkeypatch):
    import json
    import api.mock104 as portal
    import recruitment.computer_use as worker
    from tests.test_mock104 import job
    approved=job(required_skills=['html、css'],trainable_skills=[],work_hours='09:00–18:00')
    run=client.post('/api/mock104/agent/approve',json={'job':approved,'hr_confirmed':True,'fill_only':True}).json()
    cookie=client.cookies.get(portal.COOKIE);identifier=[];goals=[]
    def state():
        with portal.sessions.session(cookie) as session:return session['agent_run']
    def click(x,y):
        if not identifier:
            response=client.post('/api/mock104/jobs',json={**approved,'required_skills':['html','css']})
            identifier.append(response.json()['selected_id'])
        else:assert client.put('/api/mock104/jobs/'+identifier[0],json=approved).status_code==200
    page=SimpleNamespace(route=lambda *a:None,on=lambda *a:None,goto=lambda *a,**kw:None,
        url='http://127.0.0.1:8891/mock104#new',is_closed=lambda:state()['phase'] in {'FILLED','REVIEW_REQUIRED'},
        screenshot=lambda **kw:b'jpeg',wait_for_timeout=lambda _:None,mouse=SimpleNamespace(click=click))
    browser=SimpleNamespace(new_context=lambda **kw:SimpleNamespace(add_cookies=lambda *a:None,new_page=lambda:page),close=lambda:None)
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=lambda:nullcontext(SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw:browser)))))
    monkeypatch.setattr(worker.time,'sleep',lambda _:None)
    def decide(screenshot,data,goal,error):
        goals.append(goal)
        assert len(goals)==1
        return {'actions':[{'type':'click','x':10,'y':20}]}
    monkeypatch.setattr(worker,'decide',decide)
    worker.operate(portal.sessions,cookie,'http://127.0.0.1:8891',run['run_id'])
    assert state()['phase']=='REVIEW_REQUIRED' and len(goals)==1
    assert list(state()['mismatches'])==['required_skills']
    assert state()['job_id']==identifier[0]
