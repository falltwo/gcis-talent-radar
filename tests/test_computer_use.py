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


def test_external_verifier_reads_saved_normal_webpage_data(client):
    import api.mock104 as portal
    from recruitment.computer_use import saved_job
    identifier=create(client,salary_mode='NEGOTIABLE',salary_min=None,salary_max=None)
    service=next(iter(portal.sessions.sessions.values()))['service']
    actual=saved_job(service,identifier)
    assert actual['salary_mode']=='NEGOTIABLE'
    assert actual['salary_min'] is None and actual['salary_max'] is None
    assert actual['company_name']=='虛構示範企業'


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
