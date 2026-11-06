from concurrent.futures import ThreadPoolExecutor
import time
from recruitment.backend.workflow import ConversationWorkflow


def handle(memory,event):
    memory['count']=memory.get('count',0)+1
    return {'memory':memory,'result':{'kind':'ack','count':memory['count'],'message':event['message']}}


def event(text,request_id):
    return {'message':text,'request_id':request_id,'district':''}


def test_graph_pauses_and_resumes_from_persistent_checkpoint(tmp_path):
    path=tmp_path/'workflow.sqlite'
    first=ConversationWorkflow(path)
    assert first.run('owner-a',event('hello','1'),handle)['result']['count']==1
    assert first.graph.get_state({'configurable':{'thread_id':'owner-a'}}).interrupts
    first.close()
    resumed=ConversationWorkflow(path)
    assert resumed.peek('owner-a')['result']['count']==1
    assert resumed.run('owner-a',event('continue','2'),handle)['result']['count']==2
    assert resumed.peek('other-owner')=={}
    resumed.close()


def test_same_conversation_turns_are_serialized(tmp_path):
    workflow=ConversationWorkflow(tmp_path/'workflow.sqlite')
    def slow(memory,message):
        time.sleep(.02)
        return handle(memory,message)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda n:workflow.run('one-owner',event(str(n),str(n)),slow),[1,2]))
    assert sorted(r['result']['count'] for r in results)==[1,2]
    workflow.close()


def test_callbacks_and_credentials_are_not_checkpointed(tmp_path):
    path=tmp_path/'workflow.sqlite'
    workflow=ConversationWorkflow(path)
    secret='do-not-store-this-model-key'
    def callback(memory,message):
        assert secret
        return handle(memory,message)
    workflow.run('owner',event('hello','1'),callback)
    workflow.close()
    assert secret.encode() not in path.read_bytes()


def test_failed_turn_is_resumed_before_accepting_another_message(tmp_path):
    workflow=ConversationWorkflow(tmp_path/'workflow.sqlite')
    calls=[]
    def flaky(memory,message):
        calls.append(message['request_id'])
        if len(calls)==1:raise RuntimeError('temporary failure')
        return handle(memory,message)
    import pytest
    with pytest.raises(RuntimeError):workflow.run('owner',event('first','1'),flaky)
    result=workflow.run('owner',event('second','2'),flaky)
    assert calls==['1','1','2']
    assert result['result']['count']==2
    workflow.close()
