from types import SimpleNamespace

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
