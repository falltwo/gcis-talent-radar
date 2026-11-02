import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import recruitment.job_research as research
from api.recruitment_agent import AgentPrepare
from recruitment.models import Requirement
from tests.test_mock104 import client


def test_accounting_sparse_needs_preserves_headcount_and_negotiable_salary(client):
    response=client.post('/api/mock104/agent/prepare',json={'mode':'AUTO','role':'會計','district':'大雅區','needs':'招募三人，月薪面議'})
    assert response.status_code==200,response.text
    result=response.json();job=result['job']
    assert job['headcount']==3
    assert job['salary_mode']=='NEGOTIABLE'
    assert job['salary_min'] is None and job['salary_max'] is None
    assert result['field_provenance']['headcount']=='HR_INPUT'
    assert result['field_provenance']['work_hours']=='SUGGESTED'
    assert result['sources'][0]['url'].startswith('https://www.onetonline.org/')
    assert '招募三人' in job['description']
    Requirement.model_validate({k:v for k,v in job.items() if k in Requirement.model_fields})


def test_explicit_work_conditions_override_template():
    body=AgentPrepare(role='會計',district='西屯區',needs='招募5人，月薪40000至50000元，排班制，晚班18:00至23:00，至少2年工作經驗')
    result=research.draft_job(body)['job']
    assert result['headcount']==5
    assert result['salary_min']==40000 and result['salary_max']==50000
    assert result['salary_mode']=='RANGE'
    assert result['schedule_system']=='排班制'
    assert result['shift']=='晚班'
    assert result['work_hours']=='18:00–23:00'
    assert result['min_experience_months']==24


def test_quantum_role_calls_live_search_and_requires_citations(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only')
    observed=[]
    content={'description':'研究量子演算法，建立模擬與驗證流程。研究方向需HR確認。','required_skills':['量子力學','Python'],'trainable_skills':['團隊研究工具'],'review_notes':['請確認是硬體或演算法方向。']}
    def post(*a,**kw):
        observed.append(kw['json'])
        return SimpleNamespace(ok=True,json=lambda:{'choices':[{'message':{'content':json.dumps(content),'annotations':[{'type':'url_citation','url_citation':{'url':'https://research.example.edu/quantum/jobs','title':'Research careers'}}]}}]})
    monkeypatch.setattr(research.requests,'post',post)
    result=research.draft_job(AgentPrepare(role='量子研究師',district='大雅區',needs='招募三人，月薪面議'))
    assert result['source']=='LIVE_WEB_RESEARCH'
    assert result['sources'][0]['url'].startswith('https://research.example.edu')
    assert observed[0]['plugins'][0]['id']=='web'
    assert result['job']['salary_min'] is None


def test_uncited_search_is_rejected_not_silently_templated(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only')
    monkeypatch.setattr(research.requests,'post',lambda *a,**k:SimpleNamespace(ok=True,json=lambda:{'choices':[{'message':{'content':'{}','annotations':[]}}]}))
    with pytest.raises(HTTPException) as error: research.research_role('未知冷門職位')
    assert error.value.status_code==502


@pytest.mark.parametrize('url',['http://example.com/a','https://127.0.0.1/x','https://localhost/x','javascript:alert(1)'])
def test_source_links_reject_local_or_unsafe_urls(url):
    assert research.safe_source({'url':url}) is None


def test_negotiable_salary_cannot_invent_range():
    with pytest.raises(ValueError):
        Requirement(title='會計',district='大雅區',shift='日班',headcount=3,salary_mode='NEGOTIABLE',salary_min=30000,salary_max=40000)
