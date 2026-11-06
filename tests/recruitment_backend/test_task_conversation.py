from fastapi.testclient import TestClient
from test_api import c,account
from test_memory import say
from recruitment.backend.main import create_app


def test_bare_headcount_completes_waiting_role_with_salary_reference(c,monkeypatch):
    monkeypatch.setattr('recruitment.backend.main.search_answer',lambda *a:{'message':'資訊','sources':[]})
    h=account(c)
    first=say(c,h,'在太平區設廠，想招現場技術人員；當地起薪中位數31,500元，薪資請參考')
    assert first['kind']=='clarify'
    assert first['context']['pending_question']['field']=='quantity'
    assert say(c,h,'工作內容有哪些？')['kind']=='answer'
    result=say(c,h,'5')
    assert result['kind']=='batch'
    item,=result['batch']['items']
    assert (item['title'],item['quantity'],item['location'])==('現場技術人員',5,'太平區')
    assert item['salary_min'] is None


def test_bare_number_is_not_invented_headcount_without_pending_question(c):
    assert say(c,account(c),'5')['kind']=='clarify'


def test_pending_headcount_preserves_reference_qualifier_and_complete_field_values(c):
    h=account(c)
    say(c,h,'想招現場技術人員；月薪31500元，僅供參考；工作內容：維修機台，協助生產；任職條件：熟悉薪資行情，具備溝通能力')
    item,=say(c,h,'5')['batch']['items']
    assert item['salary_min'] is None
    assert item['description']=='維修機台，協助生產'
    assert item['requirements']=='熟悉薪資行情，具備溝通能力'


def test_pending_headcount_preserves_explicit_employer_salary(c):
    h=account(c)
    say(c,h,'想招現場技術人員；月薪4萬；工作內容：維修機台，協助生產')
    item,=say(c,h,'5')['batch']['items']
    assert (item['salary_min'],item['salary_max'])==(40000,40000)
    assert item['description']=='維修機台，協助生產'


def test_reference_qualifier_before_salary_cannot_approve_employer_salary(c):
    h=account(c)
    say(c,h,'想招現場技術人員；以下僅供參考，月薪31500元')
    item,=say(c,h,'5')['batch']['items']
    assert item['salary_min'] is None and not item['salary_confirmed']


def test_salary_after_content_is_not_absorbed_into_content(c):
    h=account(c)
    say(c,h,'想招現場技術人員；工作內容：維修機台，協助生產；月薪4萬')
    item,=say(c,h,'5')['batch']['items']
    assert item['description']=='維修機台，協助生產'
    assert item['salary_min']==item['salary_max']==40000


def test_waiting_task_survives_restart_and_is_owner_scoped(c):
    h=account(c)
    say(c,h,'在太平區設廠，想招現場技術人員')
    url=str(c.app.state.engine.url)
    with TestClient(create_app(url)) as restarted:
        assert say(restarted,h,'5','other-tab')['kind']=='clarify'
        result=say(restarted,h,'5')
        assert result['kind']=='batch'
        assert result['batch']['items'][0]['quantity']==5


def test_pre_graph_pending_task_can_resume_after_chat_expiry(c):
    from datetime import datetime,timedelta,timezone
    from sqlalchemy import select
    from recruitment.backend.models import AssistantMemory,User
    h=account(c)
    with c.app.state.session_factory() as session:
        user=session.scalar(select(User))
        session.add(AssistantMemory(company_id=user.company_id,user_id=user.id,conversation_id='tab-a',state={'pending_requests':['在太平區設廠，想招現場技術人員'],'messages':[]},expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
        session.commit()
    item,=say(c,h,'5')['batch']['items']
    assert (item['title'],item['quantity'],item['location'])==('現場技術人員',5,'太平區')


def test_same_request_replay_returns_same_batch_and_conflicting_payload_is_rejected(c):
    h=account(c)
    body={'message':'前端工程師1位，月薪4萬','conversation_id':'replay','request_id':'one-turn'}
    first=c.post('/assistant',headers=h,json=body)
    assert first.status_code==200,first.text
    again=c.post('/assistant',headers=h,json=body)
    assert again.status_code==200,again.text
    assert again.json()['batch']['id']==first.json()['batch']['id']
    assert len(c.get('/batches',headers=h).json())==1
    conflict=c.post('/assistant',headers=h,json={**body,'message':'前端工程師2位'})
    assert conflict.status_code==409


def test_clearing_task_removes_pending_question(c):
    h=account(c)
    say(c,h,'在太平區設廠，想招現場技術人員')
    say(c,h,'清除記憶')
    assert say(c,h,'5')['kind']=='clarify'


def test_old_request_replay_after_another_turn_does_not_duplicate_or_rewind(c):
    h=account(c)
    body={'message':'前端工程師1位，月薪4萬','conversation_id':'replay','request_id':'first'}
    first=c.post('/assistant',headers=h,json=body).json()
    changed=c.post('/assistant',headers=h,json={**body,'message':'月薪5萬','request_id':'second'}).json()
    assert c.post('/assistant',headers=h,json=body).json()['batch']['id']==first['batch']['id']
    task=c.get('/assistant/task',headers=h,params={'conversation_id':'replay'}).json()
    assert task['batch_id']==changed['batch']['id'] and task['items'][0]['salary_min']==50000
    other=account(c,'task-other@example.com')
    assert c.get('/assistant/task',headers=other,params={'conversation_id':'replay'}).json()['items']==[]
    assert len(c.get('/batches',headers=h).json())==2


def test_committed_turn_is_not_repeated_after_checkpoint_failure(c,monkeypatch):
    from sqlalchemy import select,func
    from recruitment.backend.models import AssistantTurn
    h=account(c);failed=[]
    saver=c.app.state.workflow.saver;put=saver.put
    def fail_after_commit(*args,**kwargs):
        with c.app.state.session_factory() as session:committed=session.scalar(select(func.count()).select_from(AssistantTurn))
        if committed and not failed:
            failed.append(True);raise OSError('simulated checkpoint write failure')
        return put(*args,**kwargs)
    monkeypatch.setattr(saver,'put',fail_after_commit)
    body={'message':'前端工程師1位，月薪4萬','conversation_id':'crash','request_id':'first'}
    assert c.post('/assistant',headers=h,json=body).status_code==500
    assert c.post('/assistant',headers=h,json=body).status_code==200
    assert len(c.get('/batches',headers=h).json())==1
    changed=c.post('/assistant',headers=h,json={**body,'message':'月薪5萬','request_id':'second'})
    assert changed.status_code==200,changed.text
    assert changed.json()['batch']['items'][0]['salary_min']==50000
    assert len(c.get('/batches',headers=h).json())==2
