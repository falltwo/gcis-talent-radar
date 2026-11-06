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


@pytest.mark.parametrize('text',[
    '請問可以幫我招募一個前端工程師，月薪5萬嗎',
    '幫我招募2位品管員，任職條件熟悉如何操作量測儀器',
    '幫我招募2位品管員，工作內容是說明如何操作量測儀器',
])
def test_polite_creation_and_assigned_prose_do_not_become_search(c,monkeypatch,text):
    monkeypatch.setattr('recruitment.backend.main.search_answer',lambda *a:
        (_ for _ in ()).throw(AssertionError('creation must not call search')))
    result=say(c,account(c),text)
    assert result['kind']=='batch'


def test_named_headcount_update_preserves_other_role_and_salary(c):
    h=account(c)
    say(c,h,'前端工程師與全端工程師各5位，月薪各5萬')
    changed=say(c,h,'全端工程師改成3位')
    assert [(i['title'],i['quantity'],i['salary_min']) for i in changed['batch']['items']]==[
        ('前端工程師',5,50000),('全端工程師',3,50000)]
    changed=say(c,h,'前端工程師月薪6萬')
    assert [(i['title'],i['quantity'],i['salary_min']) for i in changed['batch']['items']]==[
        ('前端工程師',5,60000),('全端工程師',3,50000)]
    before=len(c.get('/batches',headers=h).json())
    assert say(c,h,'不存在的工程師改成4位')['kind']=='clarify'
    assert len(c.get('/batches',headers=h).json())==before


@pytest.mark.parametrize('confirmation',['yes','YES','ok','好','確認'])
def test_confirmation_does_not_create_or_reextract_batch(c,confirmation):
    h=account(c)
    say(c,h,'招募一個前端工程師，月薪5萬，公司名稱是大安有限公司')
    say(c,h,'工作內容是維護訂單系統與API')
    say(c,h,'地點改到台中市南區')
    before=c.get('/batches',headers=h).json()
    result=say(c,h,confirmation)
    assert result['kind']=='ack' and 'batch' not in result
    assert c.get('/batches',headers=h).json()==before
    changed=say(c,h,'月薪6萬')
    item,=changed['batch']['items']
    assert item['location']=='台中市南區' and item['description']=='維護訂單系統與API'


def test_confirmation_does_not_approve_unassigned_salary(c):
    h=account(c)
    say(c,h,'前端工程師與全端工程師各5位，月薪各5萬')
    assert say(c,h,'月薪6萬')['kind']=='clarify'
    assert say(c,h,'yes')['kind']=='clarify'
    changed=say(c,h,'全部適用')
    assert [i['salary_min'] for i in changed['batch']['items']]==[60000,60000]


def test_pending_intake_can_be_completed_after_questions_and_restart(c,monkeypatch):
    from fastapi.testclient import TestClient
    from recruitment.backend.main import create_app
    monkeypatch.setattr('recruitment.backend.main.search_answer',lambda *a:{'message':'工作資訊','sources':[]})
    h=account(c)
    assert say(c,h,'我要在南區設廠，招募品管員')['kind']=='clarify'
    for _ in range(8):assert say(c,h,'品管員的工作內容')['kind']=='answer'
    with TestClient(create_app(str(c.app.state.engine.url))) as restarted:
        # Completing known pending evidence must not let a provider turn
        # "南區" into "工作地點：南區" or re-interpret the headcount.
        monkeypatch.setattr(restarted.app.state.ai,'structured',lambda *a:
            (_ for _ in ()).throw(AssertionError('pending fields already validated')))
        changed=say(restarted,h,'20位')
        assert changed['kind']=='batch'
        item,=changed['batch']['items']
        assert (item['title'],item['quantity'],item['location'])==('品管員',20,'南區')
        changed=say(restarted,h,'月薪4萬')
        assert changed['batch']['items'][0]['salary_min']==40000


@pytest.mark.parametrize('prefix',['想招','想招募','我想招','我想招募','想要招','我們想招','我要招募'])
def test_hiring_request_prefix_is_not_part_of_occupation(prefix):
    from recruitment.backend.parser import parse
    row,=parse('在太平區設廠，'+prefix+'現場技術人員5人')
    assert (row['title'],row['quantity'],row['location'])==('現場技術人員',5,'太平區')
    rows=parse(prefix+'現場技術人員與品管員各5人')
    assert [r['title'] for r in rows]==['現場技術人員','品管員']


def test_bad_model_title_cannot_override_correct_hiring_prefix_parser(c,monkeypatch):
    from recruitment.backend.ai import Extraction
    text='在太平區設廠，想招現場技術人員5人'
    h=account(c)
    monkeypatch.setattr(c.app.state.ai,'mode','auto')
    monkeypatch.setattr(c.app.state.ai,'key','test-only')
    def structured(schema,system,data):
        assert schema is Extraction
        return Extraction(items=[dict(title='想招現場技術人員',quantity=5,quantity_text='5',
            evidence=text,description='',requirements='',location='太平區')],clarification='')
    monkeypatch.setattr(c.app.state.ai,'structured',structured)
    result=say(c,h,text)
    row,=result['batch']['items']
    assert (row['title'],row['quantity'],row['location'])==('現場技術人員',5,'太平區')
    assert result['batch']['ai']['fallback_reason']=='invalid_job_title'


@pytest.mark.parametrize('prefix',['想招','想招募'])
def test_want_to_hire_pending_role_can_be_completed(c,prefix):
    h=account(c)
    assert say(c,h,'在太平區設廠，'+prefix+'現場技術人員')['kind']=='clarify'
    row,=say(c,h,'5人')['batch']['items']
    assert (row['title'],row['quantity'],row['location'])==('現場技術人員',5,'太平區')
