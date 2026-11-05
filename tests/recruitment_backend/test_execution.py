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
