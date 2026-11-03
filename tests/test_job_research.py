import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import recruitment.job_research as research
from api.recruitment_agent import AgentPrepare
from recruitment.models import Requirement
from tests.test_mock104 import client


@pytest.fixture(autouse=True)
def isolated_history(monkeypatch,tmp_path):
    monkeypatch.setenv('RECRUITMENT_TEMPLATE_HISTORY_DB',str(tmp_path/'history.sqlite'))


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


@pytest.mark.parametrize(('needs','months'),[
    ('日班 工作經驗兩年以上',24),('工作至少兩年',24),('兩年以上工作經驗',24),
    ('至少兩年相關工作經驗',24),('需具備2年工作經驗',24),('工作經驗：２年以上',24),
    ('工作經驗二年以上',24),('年資至少三年',36),('經驗至少十年',120),
    ('至少十二年工作經驗',144),('工作經驗二十五年以上',300),
    ('工作經驗一年半以上',18),('半年工作經驗',6),('工作經驗2.5年以上',30),
    ('工作經驗不限',0),('經驗不拘',0),
])
def test_experience_supports_chinese_numerals_and_word_order(needs,months):
    assert research.explicit_conditions(needs)['min_experience_months']==months


@pytest.mark.parametrize('needs',[
    '公司成立兩年，招募三人','招募兩人，日班','公司於2024年成立',
    '工作經驗兩年以下','最多兩年工作經驗','不需要兩年工作經驗',
])
def test_unrelated_or_negated_years_do_not_become_experience_minimums(needs):
    assert 'min_experience_months' not in research.explicit_conditions(needs)


def test_chinese_experience_is_preserved_as_hr_input(client):
    response=client.post('/api/mock104/agent/prepare',json={'role':'會計','district':'大里區','needs':'日班 工作經驗兩年以上'})
    assert response.status_code==200,response.text
    draft=response.json()
    assert draft['job']['min_experience_months']==24
    assert draft['field_provenance']['min_experience_months']=='HR_INPUT'


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


@pytest.mark.parametrize('role',list(research.TEMPLATES))
def test_common_roles_use_valid_templates_without_network(client, monkeypatch, role):
    from api.mock104 import JobForm
    monkeypatch.setenv('RECRUITMENT_AGENT_DEMO_AI_ENABLED','0')
    def unexpected_search(*args, **kwargs):
        raise AssertionError('A common template must not call web research')
    monkeypatch.setattr(research.requests,'post',unexpected_search)
    result=client.post('/api/mock104/agent/prepare',json={'role':role,'district':'西屯區','needs':'招募三人，月薪面議'})
    assert result.status_code==200,result.text
    draft=result.json()
    assert draft['source']=='OCCUPATIONAL_TEMPLATE'
    assert draft['template_name']==role
    assert draft['job']['headcount']==3 and draft['job']['salary_min'] is None
    assert draft['sources'][0]['status']=='CURATED_REFERENCE'
    JobForm.model_validate(draft['job'])


def test_aliases_are_unambiguous_and_all_resolve():
    seen={}
    for name,template in research.TEMPLATES.items():
        for alias in template['aliases']:
            key=research.normalize_role(alias)
            assert key not in seen or seen[key]==name
            seen[key]=name
            assert research.find_template(alias)[0]==name
    assert research.find_template(' 企劃　助理 ')[0]=='企劃助理'
    assert research.find_template('ＣＮＣ　操作員')[0]=='CNC操作員'
    assert research.find_template('Front End Engineer')[0]=='前端工程師'
    assert research.find_template('量子研究師') is None
    assert research.find_template('量子軟體工程師') is None


def test_planning_assistant_does_not_inherit_marketing_requirements():
    draft=research.draft_job(AgentPrepare(role='企劃助理',district='大雅區',needs='招募三人，月薪面議'))
    assert '行銷' not in '、'.join(draft['job']['required_skills'])
    assert '廣告投放' not in '、'.join(draft['job']['required_skills'])
    assert any('確認方向' in note for note in draft['review_notes'])
    assert draft['field_provenance']['required_skills']=='SUGGESTED'


def test_requested_common_titles_do_not_fall_through_to_search():
    roles=['行政助理','行政秘書','會計','財務人員','資料輸入與文書人員',
           '門市銷售人員','專櫃人員','餐飲服務人員（外場／內場）','內場人員','外場人員',
           '房仲與不動產經紀人員','業務專員','業務助理','軟體工程師','資訊工程師',
           '行銷企劃','數位行銷專員','護理師與醫事人員','護理師','醫事人員',
           '產線作業員','倉儲物流與理貨人員','司機與配送員','配送員',
           'AI工程師','數據分析師','數據工程師']
    assert all(research.has_template(role) for role in roles)


def test_different_job_scopes_keep_different_templates():
    for first,second in [('內場人員','外場人員'),('業務專員','業務助理'),
                         ('軟體工程師','資訊工程師'),('護理師','醫事人員'),
                         ('數據分析師','數據工程師')]:
        assert research.find_template(first)[0]!=research.find_template(second)[0]


def test_medical_family_requires_hr_to_identify_specialty():
    result=research.draft_job(AgentPrepare(role='醫事人員',district='西屯區',needs='招募三人，月薪面議'))
    assert result['requires_hr_review']
    assert any('尚未指定實際專業' in note for note in result['review_notes'])
    assert not any('診斷' in skill or '處方' in skill for skill in result['job']['required_skills'])


def test_strategy_reports_template_or_live_search_without_using_network(client, monkeypatch):
    monkeypatch.setattr(research.requests,'post',lambda *a,**k:pytest.fail('Strategy must not perform research'))
    result=client.get('/api/mock104/agent/strategy',params={'role':'測試員'})
    assert result.json()=={'source':'OCCUPATIONAL_TEMPLATE','template_name':'測試員','max_wait_seconds':15}
    result=client.get('/api/mock104/agent/strategy',params={'role':'量子研究師'})
    assert result.json()=={'source':'LIVE_WEB_RESEARCH','template_name':None,'max_wait_seconds':60}
    assert client.get('/api/mock104/agent/strategy',params={'role':'x'*121}).status_code==422


def test_research_timeout_is_reported_without_returning_fake_suggestions(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only')
    def timeout(*args,**kwargs):
        assert kwargs['timeout']==(5,45)
        raise research.requests.Timeout()
    monkeypatch.setattr(research.requests,'post',timeout)
    with pytest.raises(HTTPException) as error:
        research.research_role('未知專業職位')
    assert error.value.status_code==502
    assert '逾時' in error.value.detail


def test_general_tester_does_not_require_software_programming():
    draft=research.draft_job(AgentPrepare(role='測試員',district='西屯區',needs='招募一人月薪面議'))
    assert draft['source']=='OCCUPATIONAL_TEMPLATE'
    assert draft['job']['headcount']==1 and draft['job']['salary_min'] is None
    assert '程式設計' not in draft['job']['required_skills']
    assert any('確認領域' in note for note in draft['review_notes'])
