import pytest
from recruitment.backend.salary import verified_salary
from recruitment.backend.parser import parse
from test_api import c


@pytest.mark.parametrize('phrase,low,high',[
    ('月薪4到6萬',40000,60000),('月薪4.5到6萬',45000,60000),('薪資五萬',50000,50000),('薪水4.5萬至6.5萬',45000,65000),
    ('月薪四萬五千到六萬',45000,60000),('月薪40,000至60,000元',40000,60000),
    ('月薪５萬～６萬',50000,60000),('月薪4萬5千到6萬',45000,60000),
])
def test_natural_salary_formats(phrase,low,high):
    job=parse('2位工程師，'+phrase)[0]
    assert (job['salary_min'],job['salary_max'])==(low,high)
    assert job['salary_type']=='monthly'


def test_shared_salary_and_different_named_salaries():
    jobs=parse('2位前端工程師、2位全端工程師，兩個職位各5萬')
    assert [j['salary_min'] for j in jobs]==[50000,50000]
    jobs=parse('2位前端工程師、2位全端工程師，前端工程師薪資五萬、全端工程師薪資六萬')
    assert [j['salary_min'] for j in jobs]==[50000,60000]


def test_ambiguous_multi_job_salary_and_conflicts_ask_instead_of_guessing():
    for text in ['2位工程師、2位會計，月薪5萬','2位工程師，工程師月薪5萬，工程師月薪6萬']:
        with pytest.raises(ValueError):parse(text)


@pytest.mark.parametrize('salary',['月薪4k','月薪4,50','月薪4.5元','月薪4萬至未知','月薪6萬到4萬','月薪5萬以上','月薪0'])
def test_partial_or_invalid_amount_is_never_accepted(salary):
    with pytest.raises(ValueError):parse('2位工程師，'+salary)


def test_pending_salary_blocks_template_substitution(c):
    from test_api import account,template
    h=account(c);template(c,h,title='工程師',salary=80000)
    response=c.post('/batches',headers=h,json={'message':'2位工程師，薪資先留白'})
    assert response.status_code==201,response.text
    item=response.json()['items'][0]
    assert item['salary_min'] is None and item['salary_confirmed'] is False


def test_salary_periods_are_not_converted_to_monthly():
    assert verified_salary('工程師年薪120萬',['工程師'])['工程師']['salary_type']=='yearly'
    assert verified_salary('工程師時薪200元',['工程師'])['工程師']['salary_type']=='hourly'


def test_latest_user_turn_replaces_salary_without_changing_other_role():
    from recruitment.backend.salary import salary_from_turns
    result=salary_from_turns(['前端工程師月薪4萬，網路管理師月薪5萬','前端工程師月薪6萬'],['前端工程師','網路管理師'])
    assert result['前端工程師']['salary_min']==60000
    assert result['網路管理師']['salary_min']==50000
    with pytest.raises(ValueError):salary_from_turns(['工程師月薪5萬，工程師月薪6萬'],['工程師'])


def test_model_can_map_colloquial_role_names_without_changing_amounts():
    from types import SimpleNamespace
    def structured(schema,system,data):
        assert [m['low'] for m in data['mentions']]==[50000,60000]
        return schema.model_validate({'assignments':[{'mention_id':0,'titles':['前端工程師']},{'mention_id':1,'titles':['全端工程師']}],'clarification':''})
    result=verified_salary('前端5萬、全端6萬',['前端工程師','全端工程師'],SimpleNamespace(structured=structured))
    assert result['前端工程師']['salary_min']==50000
    assert result['全端工程師']['salary_min']==60000
