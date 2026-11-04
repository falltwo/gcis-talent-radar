import json
import sqlite3
from types import SimpleNamespace

import pytest

import recruitment.job_research as research
from recruitment.job_history import JobHistory
from tests.test_mock104 import client


@pytest.fixture(autouse=True)
def isolated_history(monkeypatch,tmp_path):
    monkeypatch.setenv('RECRUITMENT_TEMPLATE_HISTORY_DB',str(tmp_path/'history.sqlite'))
    monkeypatch.setenv('RECRUITMENT_AGENT_DEMO_AI_ENABLED','1')
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only')


CONTENT={'description':'整理專業研究資料，依專案計畫設計實驗及驗證流程。',
         'required_skills':['資料分析','研究紀錄'], 'trainable_skills':['團隊工具'],
         'review_notes':['請確認研究方向。']}
SOURCE={'url':'https://research.example.edu/jobs','title':'研究職務','retrieved_at':'2026-11-03T00:00:00+00:00'}


def mock_provider(monkeypatch,**overrides):
    calls=[]
    def post(*a,**kw):
        calls.append(kw['json'])
        payload={'choices':[{'message':{'content':json.dumps(CONTENT),'annotations':[{'url_citation':SOURCE}]}}],
                 'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150,'cost':0.007}}
        payload.update(overrides)
        return SimpleNamespace(ok=True,json=lambda:payload)
    monkeypatch.setattr(research.requests,'post',post)
    return calls


def test_successful_search_is_reused_without_key_or_new_hr_data_leaking(client,monkeypatch):
    calls=mock_provider(monkeypatch)
    first=client.post('/api/mock104/agent/prepare',json={'role':'專業研究員','district':'大里區','company_name':'甲公司秘密名稱','needs':'招募三人 月薪面議'}).json()
    assert first['source']=='LIVE_WEB_RESEARCH' and first['history_saved']
    assert first['usage']['total_tokens']==150 and first['usage']['cost_usd']==0.007
    monkeypatch.setenv('RECRUITMENT_AGENT_DEMO_AI_ENABLED','0')
    monkeypatch.delenv('OPENROUTER_API_KEY')
    second=client.post('/api/mock104/agent/prepare',json={'role':'專業　研究員','district':'西屯區','company_name':'乙公司','needs':'招募2人 月薪4萬到六萬 晚班 兩年以上工作經歷'})
    assert second.status_code==200,second.text
    draft=second.json()
    assert len(calls)==1
    assert draft['source']=='HISTORICAL_TEMPLATE'
    assert draft['usage']==research.local_usage()
    assert draft['job']['headcount']==2 and draft['job']['salary_min']==40000
    assert draft['job']['salary_max']==60000
    assert draft['field_provenance']['salary_min']=='HR_INPUT'
    assert draft['field_provenance']['salary_max']=='HR_INPUT'
    assert draft['job']['shift']=='晚班' and draft['job']['company_name']=='乙公司'
    assert draft['job']['min_experience_months']==24
    assert draft['field_provenance']['min_experience_months']=='HR_INPUT'
    assert '招募三人' not in draft['job']['description']
    assert draft['sources'][0]['status']=='HISTORICAL_REFERENCE'
    assert draft['sources'][0]['retrieved_at']==first['sources'][0]['retrieved_at']
    raw=json.dumps(JobHistory().items(),ensure_ascii=False)
    assert '甲公司秘密名稱' not in raw and '招募三人' not in raw
    strategy=client.get('/api/mock104/agent/strategy',params={'role':'專業研究員'}).json()
    assert strategy['source']=='HISTORICAL_TEMPLATE' and strategy['max_wait_seconds']==15
    history=client.get('/api/mock104/agent/history').json()
    assert history['items'][0]['role']=='專業研究員'
    assert 'content' not in history['items'][0]
    assert history['retention_days']==30


def test_expired_history_requires_research_again(client,monkeypatch):
    calls=mock_provider(monkeypatch)
    body={'role':'專業研究員','district':'大里區','needs':'招募三人月薪面議'}
    assert client.post('/api/mock104/agent/prepare',json=body).status_code==200
    with sqlite3.connect(JobHistory().path) as conn:
        conn.execute('UPDATE job_template_history SET expires_at=0')
    assert client.get('/api/mock104/agent/history').json()['items']==[]
    response=client.post('/api/mock104/agent/prepare',json=body)
    assert response.json()['source']=='LIVE_WEB_RESEARCH'
    assert len(calls)==2


def test_research_without_citations_does_not_save_history(client,monkeypatch):
    mock_provider(monkeypatch,choices=[{'message':{'content':json.dumps(CONTENT),'annotations':[]}}])
    result=client.post('/api/mock104/agent/prepare',json={'role':'專業研究員','district':'大里區','needs':'招募三人月薪面議'})
    assert result.status_code==502
    assert JobHistory().items()==[]


def test_usage_is_unknown_when_provider_does_not_report_it(client,monkeypatch):
    mock_provider(monkeypatch,usage={})
    result=client.post('/api/mock104/agent/prepare',json={'role':'專業研究員','district':'大里區','needs':'招募三人月薪面議'}).json()
    assert result['usage']['model_called'] is True
    assert result['usage']['total_tokens'] is None and result['usage']['cost_usd'] is None


def test_history_write_failure_does_not_discard_valid_research(client,monkeypatch):
    mock_provider(monkeypatch)
    monkeypatch.setattr(JobHistory,'save',lambda *a:False)
    result=client.post('/api/mock104/agent/prepare',json={'role':'專業研究員','district':'大里區','needs':'招募三人月薪面議'}).json()
    assert result['source']=='LIVE_WEB_RESEARCH' and not result['history_saved']
    assert any('未能保存' in note for note in result['review_notes'])


def test_history_is_persistent_bounded_and_corrupt_rows_are_ignored(monkeypatch):
    monkeypatch.setattr('recruitment.job_history.MAX_ITEMS',2)
    for i in range(3):assert JobHistory().save(str(i),f'職位{i}',CONTENT,[SOURCE])
    assert len(JobHistory().items())==2
    with sqlite3.connect(JobHistory().path) as conn:
        conn.execute("UPDATE job_template_history SET payload='invalid json' WHERE role_key='2'")
    assert len(JobHistory().items())==1
    assert JobHistory().save('3','職位3',{**CONTENT,'company_name':'不應保存'},[SOURCE])
    assert 'company_name' not in json.dumps(JobHistory().get('3'))
