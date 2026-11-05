import json
import httpx
import pytest
from recruitment.backend.ai import RecruitmentAI, AIError
from test_api import c, account, template

@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('LLM_MODE','auto')
    monkeypatch.setenv('OPENROUTER_API_KEY','test-secret-not-real')
    monkeypatch.setenv('OPENROUTER_MODEL','test/model')

def extraction(title='經理',quantity=2,evidence='兩個經理',quantity_text='兩'):
    return {'items':[{'title':title,'quantity':quantity,'quantity_text':quantity_text,'evidence':evidence,'description':'','requirements':'','location':''}],'clarification':''}

def provider(data, capture=None):
    def handle(request):
        if capture is not None: capture.append(request)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data,ensure_ascii=False)}}]})
    return httpx.MockTransport(handle)

def test_openrouter_request_and_salary_protection(enabled):
    requests=[]
    ai=RecruitmentAI(transport=provider(extraction(),requests))
    rows,meta=ai.extract('兩個經理，經理月薪十萬元')
    assert meta['mode']=='openrouter'
    assert rows[0]['salary_min']==100000
    request=requests[0]; payload=json.loads(request.content)
    assert str(request.url)=='https://openrouter.ai/api/v1/chat/completions'
    assert request.headers['authorization']=='Bearer test-secret-not-real'
    assert payload['model']=='test/model'
    assert 'temperature' not in payload  # Models may reject sampling overrides with strict routing.
    assert payload['response_format']['json_schema']['strict'] is True
    assert payload['provider']['require_parameters'] is True
    assert 'salary_min' not in payload['response_format']['json_schema']['schema']['$defs']['ExtractedItem']['properties']

def test_flexible_role_order(enabled):
    ai=RecruitmentAI(transport=provider(extraction(evidence='經理需要兩位')))
    rows,meta=ai.extract('經理需要兩位，經理的月薪是十萬元')
    assert meta['mode']=='openrouter'
    assert rows[0]['quantity']==2 and rows[0]['salary_min']==100000

def test_model_cannot_drop_or_invent_roles(enabled):
    ai=RecruitmentAI(transport=provider(extraction()))
    rows,meta=ai.extract('三個工程師、兩個經理，經理月薪十萬元')
    assert len(rows)==2 and meta['fallback_reason']=='role_mismatch'
    bad=extraction();bad['items'][0]['location']='模型虛構的地點'
    ai=RecruitmentAI(transport=provider(bad))
    rows,meta=ai.extract('兩個經理，經理月薪十萬元')
    assert 'location' not in rows[0]
    assert meta['fallback_reason']=='unverified_evidence'


def test_shared_headcount_and_command_do_not_override_correct_ai(enabled):
    text='十位前端工程師全端工程師\n各十位\n 幫我建立'
    result={'items':[
        extraction(title=title,quantity=10,quantity_text='十',evidence=text)['items'][0]
        for title in ['前端工程師','全端工程師']], 'clarification':''}
    rows,meta=RecruitmentAI(transport=provider(result)).extract(text)
    assert meta['mode']=='openrouter'
    assert [(r['title'],r['quantity']) for r in rows]==[('前端工程師',10),('全端工程師',10)]


@pytest.mark.parametrize('title',['幫我建立','前端工程師全端工程師'])
def test_wrong_instruction_or_merged_title_never_becomes_draft(enabled,title):
    text='十位前端工程師全端工程師\n各十位\n 幫我建立'
    bad=extraction(title=title,quantity=10,quantity_text='十',evidence=text)
    with pytest.raises(ValueError):RecruitmentAI(transport=provider(bad)).extract(text)

def test_salary_hallucination_rejected(enabled):
    bad=extraction();bad['items'][0]['salary_min']=50000
    rows,meta=RecruitmentAI(transport=provider(bad)).extract('兩個經理，經理月薪十萬元')
    assert rows[0]['salary_min']==100000
    assert meta['fallback_reason']=='invalid_response'
    ai=RecruitmentAI(transport=provider(extraction(evidence='經理需要兩位')))
    assert ai.extract('經理需要兩位，薪水十萬')[0][0]['salary_min']==100000

@pytest.mark.parametrize('kind',['timeout','401','429','invalid_json','truncated','error'])
def test_provider_failures_fallback(enabled,kind):
    def handle(request):
        if kind=='timeout': raise httpx.ReadTimeout('test-secret-not-real',request=request)
        if kind in ['401','429']: return httpx.Response(int(kind),json={'error':{'message':'test-secret-not-real'}})
        if kind=='invalid_json': return httpx.Response(200,text='broken')
        if kind=='error': return httpx.Response(200,json={'error':{'message':'test-secret-not-real'}})
        return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{}'}}]})
    ai=RecruitmentAI(transport=httpx.MockTransport(handle))
    rows,meta=ai.extract('兩個經理，經理月薪十萬元')
    assert meta['mode']=='rules' and meta['fallback_reason']
    assert rows[0]['salary_min']==100000
    assert 'test-secret' not in json.dumps(meta)
    with pytest.raises(ValueError): ai.extract('無法辨識的招募需求')

def test_keyless_and_disabled(monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY',raising=False)
    monkeypatch.setenv('LLM_MODE','auto')
    assert RecruitmentAI().extract('一個助理')[1]['fallback_reason']=='missing_key'
    monkeypatch.setenv('LLM_MODE','openrouter')
    with pytest.raises(ValueError): RecruitmentAI()
    monkeypatch.setenv('OPENROUTER_API_KEY','test-key')
    monkeypatch.setenv('LLM_MODE','rules')
    assert not RecruitmentAI().enabled

def test_ai_draft_and_no_salary_fabrication(c,enabled):
    h=account(c); template(c,h)
    c.app.state.ai=RecruitmentAI(transport=provider(extraction(evidence='經理需要兩位')))
    response=c.post('/batches',headers=h,json={'message':'經理需要兩位，經理的月薪是十萬元'})
    assert response.status_code==201,response.text
    body=response.json()
    assert body['ai']['mode']=='openrouter'
    assert body['items'][0]['salary_min']==100000
    assert body['status']=='draft'
    # No explicit salary: template suggestion still awaits HR, even in AI mode.
    body=c.post('/batches',headers=h,json={'message':'經理需要兩位'}).json()
    assert body['items'][0]['salary_source']=='company_template'
    assert not body['items'][0]['salary_confirmed']
    assert c.post(f'/batches/{body["id"]}/confirm',headers=h).status_code==422

def test_chat_ai_tenant_isolation_and_unknown(c,enabled):
    a=account(c); b=account(c,'second@example.com')
    template(c,a,'秘密工程師',100000)
    template(c,b,'經理',50000)
    requests=[]
    c.app.state.ai=RecruitmentAI(transport=provider({'intent':'salary','titles':['經理']},requests))
    response=c.post('/chat',headers=b,json={'message':'管理職的待遇如何？'})
    assert response.status_code==200,response.text
    body=response.json()
    assert body['parser']=='openrouter'
    assert body['company_templates'][0]['salary_min']==50000
    payload=json.loads(requests[0].content)
    user_data=json.loads(payload['messages'][1]['content'])
    assert user_data['available_titles']==['經理']
    assert '秘密工程師' not in requests[0].content.decode()
    assert '50000' not in requests[0].content.decode()
    c.app.state.ai=RecruitmentAI(transport=provider({'intent':'salary','titles':['不存在職位']}))
    body=c.post('/chat',headers=b,json={'message':'不存在職位薪水多少？'}).json()
    assert body['company_templates']==[] and '查無資料' in body['message']

def test_salary_number_cannot_become_headcount(enabled):
    bad=extraction(quantity=10,quantity_text='十',evidence='經理月薪十萬元')
    ai=RecruitmentAI(transport=provider(bad))
    with pytest.raises(ValueError): ai.extract('經理月薪十萬元')

def test_api_failure_has_no_partial_batch(c,enabled):
    h=account(c)
    def timeout(request): raise httpx.ReadTimeout('test-secret-not-real',request=request)
    c.app.state.ai=RecruitmentAI(transport=httpx.MockTransport(timeout))
    response=c.post('/batches',headers=h,json={'message':'請幫我招聘一些人'})
    assert response.status_code==422
    assert 'test-secret' not in response.text
    assert c.get('/batches',headers=h).json()==[]
    body=c.post('/batches',headers=h,json={'message':'一個助理'}).json()
    assert body['ai']['mode']=='rules' and body['ai']['fallback_reason']=='timeout'
    assert body['items'][0]['salary_min'] is None
    response=c.post('/chat',headers=h,json={'message':'助理薪資多少？'})
    assert response.status_code==200
    assert response.json()['ai']['fallback_reason']=='timeout'


def test_model_choosing_instruction_as_role_falls_back_to_verified_real_roles(enabled):
    text='我想招募前端工程師與全端工程師各5位 填寫履歷範本'
    ai=RecruitmentAI(transport=provider(extraction(title='填寫履歷範本',quantity=5,quantity_text='5',evidence=text)))
    rows,meta=ai.extract(text)
    assert [(r['title'],r['quantity']) for r in rows]==[('前端工程師',5),('全端工程師',5)]
    assert meta['mode']=='rules' and meta['fallback_reason']=='invalid_job_title'
