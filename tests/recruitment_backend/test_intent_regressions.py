"""Information questions must never create jobs or change approved conditions."""
from types import SimpleNamespace
import pytest
from test_api import c, account
from test_memory import say
from recruitment.backend.assistant import plan_request


@pytest.mark.parametrize('text',[
    '想了解一個品管員的工作內容',
    '一個前端工程師需要哪些技能',
    '一個品管員的任職條件',
    '品管員20位的工作內容',
    '想招募一個品管員，工作內容有哪些',
    '月薪5萬是否合理',
    '公司名稱是大安有限公司，請問一個品管員的工作內容',
])
@pytest.mark.parametrize('enabled',[False,True])
def test_information_cannot_become_draft_even_if_provider_misclassifies(text,enabled):
    ai=SimpleNamespace(enabled=enabled,structured=lambda *a:SimpleNamespace(
        action='draft',query='',reply='',request_indexes=[0]))
    result=plan_request(ai,[{'role':'user','content':text}])
    assert result['action']=='search'
    assert result['query']==text
    assert not result['brief']


def test_luna_still_resolves_information_followup_context():
    def structured(schema,system,data):
        assert data['user_requests'][-1]=='一個工程師需要哪些技能'
        return SimpleNamespace(action='search',query='臺中市前端工程師必要技能',reply='',request_indexes=[])
    ai=SimpleNamespace(enabled=True,structured=structured)
    result=plan_request(ai,[{'role':'user','content':'前端工程師的薪資行情'},
                            {'role':'user','content':'一個工程師需要哪些技能'}])
    assert result['query']=='臺中市前端工程師必要技能'


def test_question_does_not_modify_memory_or_create_batch(c,monkeypatch):
    queries=[]
    monkeypatch.setattr('recruitment.backend.main.search_answer',lambda ai,q:
        queries.append(q) or {'message':'工作內容與技能說明','sources':[]})
    h=account(c)
    say(c,h,'一個前端工程師，月薪4萬，公司名稱是原始公司')
    for text in ['想了解一個品管員的工作內容','月薪5萬是否合理',
                 '公司名稱是其他公司，請問一個品管員的工作內容']:
        assert say(c,h,text)['kind']=='answer'
    batches=c.get('/batches',headers=h).json()
    assert len(batches)==1
    changed=say(c,h,'月薪45000')
    assert changed['kind']=='batch'
    assert changed['context']['remembered_roles']==['前端工程師']
    assert changed['batch']['items'][0]['salary_min']==45000
    assert '公司名稱：原始公司' in changed['batch']['original_text']
    assert '其他公司' not in changed['batch']['original_text']
    assert len(queries)==3


def test_new_intake_after_questions_does_not_inherit_old_salary(c,monkeypatch):
    monkeypatch.setattr('recruitment.backend.main.search_answer',lambda *a:{'message':'資訊','sources':[]})
    h=account(c)
    say(c,h,'前端工程師與全端工程師各5位，月薪各5萬')
    assert say(c,h,'一個品管員的工作內容')['kind']=='answer'
    result=say(c,h,'一個品管員')
    assert result['kind']=='batch'
    row,=result['batch']['items']
    assert row['title']=='品管員' and row['quantity']==1
    assert row['salary_min'] is None and row['salary_max'] is None


def test_explicit_duties_are_conditions_not_search(c,monkeypatch):
    monkeypatch.setattr('recruitment.backend.main.search_answer',lambda *a:
        (_ for _ in ()).throw(AssertionError('not an information query')))
    h=account(c)
    assert say(c,h,'招募一個品管員，工作內容：檢查產品')['kind']=='batch'
    result=say(c,h,'工作內容：研究如何提升產品品質')
    assert result['kind']=='batch'
    assert result['batch']['items'][0]['description']=='研究如何提升產品品質'
