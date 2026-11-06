import pytest

@pytest.fixture(autouse=True)
def salary_source_offline(monkeypatch):
    monkeypatch.setattr('recruitment.backend.execution.get_reference',lambda *a:{'status':'unavailable','sources':[]})

from types import SimpleNamespace
from recruitment.backend.execution import prepare_execution
from test_api import c,account


def test_template_defaults_and_explicit_values_stay_per_role():
    batch={'original_text':'cnc2人、會計1人月薪45000元','items':[
        {'title':'cnc','quantity':2},
        {'title':'會計','quantity':1,'salary_min':45000,'salary_max':45000,'salary_type':'monthly'}]}
    prepared=prepare_execution(SimpleNamespace(enabled=False),batch,'測試公司','大雅區')
    cnc,accountant=[r['job'] for r in prepared]
    assert all(r['source']=='OCCUPATIONAL_TEMPLATE' for r in prepared)
    assert cnc['headcount']==2 and accountant['headcount']==1
    assert cnc['salary_mode']=='NEGOTIABLE' and cnc['salary_min'] is None
    assert accountant['salary_min']==accountant['salary_max']==45000
    assert cnc['description'] and cnc['required_skills']
    assert cnc['district']=='大雅區'


def test_unknown_role_gets_proposal_without_inventing_salary():
    prepared=prepare_execution(SimpleNamespace(enabled=False),{'original_text':'特殊職位1人','items':[{'title':'特殊職位','quantity':1}]},'公司','臺中市')
    assert prepared[0]['suggested'] is True
    assert prepared[0]['job']['salary_mode']=='NEGOTIABLE'
    assert prepared[0]['job']['description']


def test_transient_drafting_failure_is_retried_without_losing_hr_values(monkeypatch):
    from recruitment.backend.execution import JobSuggestion
    from recruitment.backend.ai import AIError
    monkeypatch.setattr('recruitment.job_research.history_for',lambda *a:None)
    calls=[]
    def structured(schema,system,data):
        calls.append(data)
        if len(calls)==1:raise AIError('timeout')
        return JobSuggestion(description='依標準流程操作現場設備並記錄作業結果。',required_skills=['設備操作'],trainable_skills=[])
    proposal,=prepare_execution(SimpleNamespace(enabled=True,structured=structured),
        {'original_text':'現場技術人員5人','items':[{'title':'現場技術人員','quantity':5,'location':'太平區'}]},'測試雇主','臺中市')
    assert len(calls)==2
    assert proposal['source']=='AI_SUGGESTION'
    assert proposal['job']['headcount']==5 and proposal['job']['district']=='太平區'
    assert proposal['job']['salary_mode']=='NEGOTIABLE'


def test_persistent_drafting_failure_uses_labeled_template_and_preserves_explicit_values(monkeypatch):
    from recruitment.backend.ai import AIError
    monkeypatch.setattr('recruitment.job_research.history_for',lambda *a:None)
    calls=[]
    def structured(*args):
        calls.append(1);raise AIError('invalid_response')
    text='公司名稱：大安有限公司，現場技術人員5人，日班，08:00-17:00'
    item={'title':'現場技術人員','quantity':5,'salary_min':50000,'salary_max':50000,'salary_type':'monthly',
          'location':'太平區','description':'依指定規範執行現場設備巡檢與維護。','requirements':'設備巡檢、異常回報'}
    proposal,=prepare_execution(SimpleNamespace(enabled=True,structured=structured),
        {'original_text':text,'items':[item]},'本機示範公司','北區')
    job=proposal['job']
    assert len(calls)==2 and proposal['source']=='GENERAL_TEMPLATE'
    assert proposal['sources']==[] and any('AI擬稿暫時未完成' in note for note in proposal['notes'])
    assert (job['company_name'],job['title'],job['headcount'],job['district'])==('大安有限公司','現場技術人員',5,'太平區')
    assert job['salary_min']==job['salary_max']==50000
    assert job['description']==item['description'] and job['required_skills']==['設備巡檢','異常回報']
    assert job['work_hours']=='08:00–17:00'


def test_execution_api_continues_with_valid_preview_when_drafting_is_unavailable(c,monkeypatch):
    from recruitment.backend.ai import AIError
    monkeypatch.setattr('recruitment.job_research.history_for',lambda *a:None)
    h=account(c)
    batch=c.post('/batches',headers=h,json={'message':'在太平區設廠，想招現場技術人員5人'}).json()
    monkeypatch.setattr(c.app.state.ai,'mode','auto');monkeypatch.setattr(c.app.state.ai,'key','test-only')
    monkeypatch.setattr(c.app.state.ai,'structured',lambda *a:(_ for _ in ()).throw(AIError('provider_http_error')))
    result=c.post('/execution/prepare',headers=h,json={'batch_id':batch['id']})
    assert result.status_code==200,result.text
    proposal,=result.json()['jobs']
    assert proposal['suggested'] and result.json()['requires_final_confirmation']
    assert proposal['job']['title']=='現場技術人員' and proposal['job']['headcount']==5
    assert proposal['job']['district']=='太平區' and proposal['job']['salary_mode']=='NEGOTIABLE'
    assert proposal['source']=='GENERAL_TEMPLATE'
    assert c.get('/job-postings',headers=h).json()==[]


def test_drafting_fallback_does_not_swallow_other_validation_errors(monkeypatch):
    monkeypatch.setattr('recruitment.job_research.history_for',lambda *a:None)
    ai=SimpleNamespace(enabled=True,structured=lambda *a:(_ for _ in ()).throw(ValueError('invalid HR data')))
    with pytest.raises(ValueError,match='invalid HR data'):
        prepare_execution(ai,{'original_text':'現場技術人員5人','items':[{'title':'現場技術人員','quantity':5}]},'測試雇主','太平區')

def test_taiwan_salary_reference_never_overwrites_employer_salary(monkeypatch):
    reference={'status':'available','sample_count':8,'salary_min':30000,'salary_max':40000,'mode':'live'}
    monkeypatch.setattr('recruitment.backend.execution.get_reference',lambda *a:reference)
    batch={'original_text':'會計1人月薪45000元','items':[{'title':'會計','quantity':1,'salary_min':45000,'salary_max':45000,'salary_type':'monthly'}]}
    proposal=prepare_execution(SimpleNamespace(enabled=False),batch,'測試公司','大雅區')[0]
    assert proposal['salary_reference']==reference
    assert proposal['job']['salary_min']==proposal['job']['salary_max']==45000


def test_old_invalid_instruction_batch_is_blocked_before_execution():
    with pytest.raises(ValueError,match='填表指令'):
        prepare_execution(SimpleNamespace(enabled=False),{'original_text':'原需求','items':[{'title':'填寫履歷範本','quantity':5}]},'公司','臺中市')


def test_named_employer_salaries_and_content_take_priority_over_templates():
    from recruitment.backend.salary import verified_salary
    text='後端工程師月薪4萬，網路管理師月薪5萬'
    titles=['後端工程師','網路管理師']
    salaries=verified_salary(text,titles)
    items=[{'title':title,'quantity':count,**salaries[title]} for title,count in zip(titles,[10,2])]
    items[0].update(description='負責公司訂單 API 與資料庫維護。',requirements='Python、PostgreSQL',location='臺中市西屯區')
    jobs=[p['job'] for p in prepare_execution(SimpleNamespace(enabled=False),{'original_text':text,'items':items},'指定企業','大雅區')]
    assert [(j['salary_min'],j['salary_max']) for j in jobs]==[(40000,40000),(50000,50000)]
    assert jobs[0]['description']==items[0]['description']
    assert jobs[0]['required_skills']==['python','postgresql']
    assert jobs[0]['district']=='臺中市西屯區'
    assert [j['headcount'] for j in jobs]==[10,2]


@pytest.mark.parametrize('text,name',[
    ('前端工程師1位 月薪4萬 公司名稱是大安有限公司','大安有限公司'),
    ('公司名稱：大安有限公司，前端工程師1位','大安有限公司'),
    ('企業名稱：星河科技 職稱：前端工程師','星河科技'),
    ('公司名稱是舊公司\n公司名稱改成大安有限公司','大安有限公司'),
])
def test_explicit_employer_name_overrides_demo_for_all_roles(text,name):
    batch={'original_text':text,'items':[{'title':'前端工程師','quantity':1},{'title':'全端工程師','quantity':2}]}
    prepared=prepare_execution(SimpleNamespace(enabled=False),batch,'本機示範公司','大雅區')
    assert [p['job']['company_name'] for p in prepared]==[name,name]


def test_execution_api_passes_employer_name_to_actual_form_without_renaming_tenant(c):
    h=account(c)
    created=c.post('/batches',headers=h,json={'message':'1位前端工程師，月薪4萬，公司名稱是大安有限公司'})
    assert created.status_code==201,created.text
    prepared=c.post('/execution/prepare',headers=h,json={'batch_id':created.json()['id'],'district':'大雅區'})
    assert prepared.status_code==200,prepared.text
    job=prepared.json()['jobs'][0]['job']
    assert job['company_name']=='大安有限公司'
    assert job['salary_min']==job['salary_max']==40000
    assert c.get('/auth/me',headers=h).json()['company_name']!='大安有限公司'


def test_model_company_name_must_have_original_user_evidence():
    from recruitment.backend.execution import employer_name,EmployerName
    ai=SimpleNamespace(enabled=True,structured=lambda *a:EmployerName(company_name='憑空公司',evidence='不存在原文'))
    with pytest.raises(ValueError,match='原始需求'):
        employer_name(ai,'我們是大安有限公司，找工程師','本機示範公司')
