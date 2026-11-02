"""Approved handoff must match visibly filled data before any mock publication."""
from collections import deque

import pytest

import api.recruitment_agent as agent
from tests.test_mock104 import client, job


def prepare(client):
    result = client.post('/api/mock104/agent/prepare', json={
        'mode':'SAMPLE', 'company_name':'虛構精密工業', 'company_intro':'虛構公司介紹',
        'district':'大雅區', 'role':'CNC 操作員', 'needs':'這是固定範例展示，不是真實職缺。',
    })
    assert result.status_code == 200, result.text
    assert result.json()['source'] == 'FIXED_SAMPLE'
    return result.json()['job']


def handoff(client, policy=True):
    data = prepare(client)
    result = client.post('/api/mock104/agent/approve',json={'job':data,'hr_confirmed':True,'confirm_before_publish':policy})
    assert result.status_code == 200, result.text
    return data,result.json()


@pytest.mark.parametrize('policy',[True,False])
def test_hr_handoff_fill_verify_and_publish(client, policy):
    data,run = handoff(client,policy)
    assert run['phase'] == 'READY'
    assert client.post('/api/mock104/agent/claim',json={'run_id':run['run_id']}).json()['phase'] == 'RUNNING'
    saved=client.post('/api/mock104/jobs',json=data).json()
    identifier=saved['selected_id']
    ready=client.post('/api/mock104/agent/filled',json={'run_id':run['run_id'],'job_id':identifier})
    assert ready.status_code == 200,ready.text
    assert ready.json()['phase'] == ('AWAITING_CONFIRMATION' if policy else 'READY_TO_PUBLISH')
    if policy:
        assert client.post(f'/api/mock104/jobs/{identifier}/submit',json={}).status_code == 409
    assert client.post(f'/api/mock104/jobs/{identifier}/submit',json={'agent_confirmation':policy}).status_code == 200
    assert client.post(f'/api/mock104/jobs/{identifier}/approve',json={}).status_code == 200
    assert client.post(f'/api/mock104/jobs/{identifier}/complete',json={}).status_code == 200
    result=client.get('/api/mock104/agent/run').json()
    assert result['phase'] == 'PUBLISHED'
    assert result['sent_to_platform'] is False


def test_second_confirmation_requires_exact_hr_approved_version(client):
    data,run=handoff(client)
    client.post('/api/mock104/agent/claim',json={'run_id':run['run_id']})
    saved=client.post('/api/mock104/jobs',json={**data,'salary_max':99999}).json()
    assert client.post('/api/mock104/agent/filled',json={'run_id':run['run_id'],'job_id':saved['selected_id']}).status_code == 409
    assert client.get('/api/mock104/state').json()['jobs'][0]['status'] == 'DRAFT'


def test_duplicate_claim_stale_id_and_cancel_block_publication(client):
    data,run=handoff(client)
    assert client.post('/api/mock104/agent/claim',json={'run_id':'old-run'}).status_code == 409
    client.post('/api/mock104/agent/claim',json={'run_id':run['run_id']})
    assert client.post('/api/mock104/agent/claim',json={'run_id':run['run_id']}).status_code == 409
    saved=client.post('/api/mock104/jobs',json=data).json()
    identifier=saved['selected_id']
    client.post('/api/mock104/agent/filled',json={'run_id':run['run_id'],'job_id':identifier})
    assert client.put(f'/api/mock104/jobs/{identifier}',json=data).status_code == 409
    assert client.post('/api/mock104/agent/cancel',json={'run_id':run['run_id']}).json()['phase'] == 'CANCELLED'
    assert client.post(f'/api/mock104/jobs/{identifier}/submit',json={'agent_confirmation':True}).status_code == 409


def test_approval_needs_hr_confirmation_and_work_hours(client):
    data=prepare(client)
    assert client.post('/api/mock104/agent/approve',json={'job':data,'hr_confirmed':False}).status_code == 422
    assert client.post('/api/mock104/agent/approve',json={'job':{**data,'work_hours':''},'hr_confirmed':True}).status_code == 422


def test_public_demo_model_calls_are_opt_in_and_bounded(client,monkeypatch):
    payload={'mode':'MODEL','company_name':'虛構公司','district':'大雅區','role':'操作員','needs':'招募3名日班操作員'}
    monkeypatch.delenv('RECRUITMENT_AGENT_DEMO_AI_ENABLED',raising=False)
    assert client.post('/api/mock104/agent/prepare',json=payload).status_code == 503
    monkeypatch.setenv('RECRUITMENT_AGENT_DEMO_AI_ENABLED','1')
    monkeypatch.setattr(agent,'model_calls',deque())
    monkeypatch.setattr(agent,'prepare_requirement',lambda text,model:{'fields':{'title':'操作員','salary_min':None}})
    for _ in range(3):
        response=client.post('/api/mock104/agent/prepare',json=payload)
        assert response.status_code == 200
        assert response.json()['job']['company_name'] == '虛構公司'
        assert response.json()['missing_fields'] == ['salary_min']
    assert client.post('/api/mock104/agent/prepare',json=payload).status_code == 429


def test_agent_page_and_scripts_are_served(client):
    assert 'HR 確認徵人條件' in client.get('/recruitment-agent').text
    assert client.get('/static/recruitment-agent.js').status_code == 200
    assert client.get('/static/mock104-agent.js').status_code == 200


def test_sample_does_not_claim_to_parse_arbitrary_roles(client):
    response=client.post('/api/mock104/agent/prepare',json={'mode':'SAMPLE','company_name':'虛構公司','district':'大雅區','role':'軟體工程師','needs':'招募軟體工程師'} )
    assert response.status_code == 422


def test_cross_origin_cannot_approve_agent_work(client):
    data=prepare(client)
    assert client.post('/api/mock104/agent/approve',json={'job':data,'hr_confirmed':True},headers={'Origin':'https://other.example'}).status_code == 403
