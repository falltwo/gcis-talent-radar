from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from fastapi.testclient import TestClient
from test_api import c,account
from recruitment.backend.models import AssistantMemory
from recruitment.backend.main import create_app


def say(c,h,text,conversation='tab-a'):
    result=c.post('/assistant',headers=h,json={'message':text,'conversation_id':conversation})
    assert result.status_code==200,result.text
    return result.json()


def test_salary_only_followup_remembers_company_place_and_content(c,monkeypatch):
    monkeypatch.setattr('recruitment.backend.execution.get_reference',lambda *a:{'status':'unavailable'})
    h=account(c)
    first=say(c,h,'前端工程師1位，月薪4萬，公司名稱是大安有限公司')
    assert first['kind']=='batch'
    say(c,h,'工作地點：臺中市西屯區')
    say(c,h,'工作內容：維護企業訂單系統與 API')
    say(c,h,'任職條件：Python、SQL')
    say(c,h,'改成5位')
    changed=say(c,h,'月薪200000')
    assert changed['kind']=='batch'
    item=changed['batch']['items'][0]
    assert (item['title'],item['quantity'],item['salary_min'],item['salary_max'])==('前端工程師',5,200000,200000)
    assert item['location']=='臺中市西屯區' and item['requirements']=='Python、SQL'
    assert item['description']=='維護企業訂單系統與 API'
    prepared=c.post('/execution/prepare',headers=h,json={'batch_id':changed['batch']['id']}).json()
    assert prepared['jobs'][0]['job']['company_name']=='大安有限公司'
    assert changed['context']['expires_in']==1800


def test_ambiguous_salary_waits_for_shared_confirmation(c):
    h=account(c)
    say(c,h,'前端工程師與全端工程師各2位，月薪各5萬')
    ambiguous=say(c,h,'月薪200000')
    assert ambiguous['kind']=='clarify'
    changed=say(c,h,'都通用')
    assert changed['kind']=='batch'
    assert [r['salary_min'] for r in changed['batch']['items']]==[200000,200000]
    changed=say(c,h,'前端工程師工作地點：臺中市西屯區')
    assert [r['location'] for r in changed['batch']['items']]==['臺中市西屯區','']


def test_context_isolated_by_conversation_and_user_and_can_be_cleared(c):
    h=account(c)
    say(c,h,'1位前端工程師，月薪4萬')
    assert say(c,h,'月薪200000','other-tab')['kind']=='clarify'
    other=account(c,'memory-other@example.com')
    assert say(c,other,'月薪200000')['kind']=='clarify'
    cleared=say(c,h,'清除記憶')
    assert cleared['context']['remembered_roles']==[]
    assert say(c,h,'月薪200000')['kind']=='clarify'


def test_expired_memory_does_not_revive_from_chat_logs(c):
    h=account(c)
    say(c,h,'1位前端工程師，月薪4萬')
    with c.app.state.session_factory() as session:
        memory=session.scalar(select(AssistantMemory))
        memory.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);session.commit()
    assert say(c,h,'月薪200000')['kind']=='clarify'
    assert len(c.get('/batches',headers=h).json())==1


def test_active_requirements_survive_many_questions_and_service_restart(c,monkeypatch):
    monkeypatch.setattr('recruitment.backend.main.search_answer',lambda *a:{'message':'查詢結果','sources':[]})
    h=account(c)
    say(c,h,'1位前端工程師，月薪4萬')
    for _ in range(8):assert say(c,h,'前端工程師的工作行情？')['kind']=='answer'
    app=create_app(str(c.app.state.engine.url))
    with TestClient(app) as restarted:
        changed=say(restarted,h,'月薪200000')
        assert changed['kind']=='batch'
        assert changed['batch']['items'][0]['salary_min']==200000
