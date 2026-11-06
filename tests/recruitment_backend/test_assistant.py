import httpx
from test_api import c, account
from recruitment.backend.assistant import search_answer, plan_request
from recruitment.backend.ai import RecruitmentAI


def test_question_never_creates_batch(c,monkeypatch):
    import recruitment.backend.main as module
    h=account(c)
    monkeypatch.setattr(module,'plan_request',lambda ai,msgs:{'action':'search','query':msgs[-1]['content']})
    monkeypatch.setattr(module,'search_answer',lambda ai,q:{'message':'查詢結果','sources':[{'title':'來源','url':'https://example.org/salary'}]})
    r=c.post('/assistant',headers=h,json={'message':'現在前端工程師平均薪資？'})
    assert r.status_code==200,r.text
    assert r.json()['kind']=='answer'
    assert c.get('/batches',headers=h).json()==[]


def test_clarification_and_followup_use_user_history(c,monkeypatch):
    import recruitment.backend.main as module
    h=account(c);seen=[]
    def planner(ai,messages):
        seen.append(messages)
        if messages[-1]['content']=='幫我建職缺表':return {'action':'clarify','reply':'請提供職稱與人數'}
        return {'action':'draft','brief':'十位軟體工程師'}
    monkeypatch.setattr(module,'plan_request',planner)
    first=c.post('/assistant',headers=h,json={'message':'幫我建職缺表'}).json()
    assert first['kind']=='clarify'
    second=c.post('/assistant',headers=h,json={'message':'十位軟體工程師'}).json()
    assert second['kind']=='batch'
    assert second['batch']['items'][0]['quantity']==10
    assert any(m['content']=='幫我建職缺表' for m in seen[-1])
    other=account(c,'other-assistant@example.com')
    c.post('/assistant',headers=other,json={'message':'幫我建職缺表'})
    assert not any(m['content']=='十位軟體工程師' for m in seen[-1])


def test_search_uses_provider_citations_and_rejects_untraceable_answer(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','test-secret')
    monkeypatch.setenv('LLM_MODE','auto')
    def transport(citations):
        def handle(request):
            assert b'"plugins"' in request.content
            assert b'"temperature"' not in request.content
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'薪資調查結果','annotations':citations}}]})
        return httpx.MockTransport(handle)
    ai=RecruitmentAI(transport=transport([{'url_citation':{'title':'薪資調查','url':'https://www.mol.gov.tw/salary'}}]))
    assert search_answer(ai,'職業工作資訊')['sources'][0]['title']=='薪資調查'
    ai.transport=transport([{'url_citation':{'url':'https://127.0.0.1/private'}}])
    result=search_answer(ai,'薪資')
    assert result['sources']==[]
    assert '薪資調查結果' not in result['message']


def test_offline_salary_question_is_search_not_draft(monkeypatch):
    monkeypatch.setattr('recruitment.taiwan_salary.get_reference',lambda *a:{'status':'no_samples'})
    monkeypatch.setenv('LLM_MODE','rules')
    ai=RecruitmentAI()
    plan=plan_request(ai,[{'role':'user','content':'現在前端工程師平均薪資'}])
    assert plan['action']=='search'
    assert search_answer(ai,plan['query'])['web_search_used'] is False


def test_repeated_shared_salary_update_and_confirmation_do_not_ask_again(c,monkeypatch):
    import recruitment.backend.main as module
    from types import SimpleNamespace
    messages=[{'role':'user','content':'前端工程師與全端工程師各10位，月薪各5萬'},
              {'role':'assistant','content':'兩筆薪資不同，請確認5萬或6萬。'},
              {'role':'user','content':'前端工程師與全端工程師各10位，月薪各6萬'},
              {'role':'assistant','content':'請確認5萬與6萬是否都適用。'},
              {'role':'user','content':'都通用'}]
    plan=plan_request(SimpleNamespace(enabled=True,structured=lambda *a:(_ for _ in ()).throw(AssertionError('No repeated clarification'))),messages)
    assert plan['action']=='draft'
    ai=RecruitmentAI();monkeypatch.setattr(ai,'key','')
    rows,_=ai.extract(plan['brief'],salary_turns=plan['salary_turns'])
    assert [(r['title'],r['quantity'],r['salary_min'],r['salary_max']) for r in rows]==[('前端工程師',10,60000,60000),('全端工程師',10,60000,60000)]
    h=account(c)
    # Keep the actual API path and rules extractor; no provider response needed.
    monkeypatch.setattr(module,'plan_request',lambda *a:plan)
    response=c.post('/assistant',headers=h,json={'message':'都通用'})
    assert response.status_code==200,response.text
    assert response.json()['kind']=='batch'
    assert [r['salary_min'] for r in response.json()['batch']['items']]==[60000,60000]


def test_new_factory_intake_ignores_prior_jobs_without_calling_intent_model():
    from types import SimpleNamespace
    ai=SimpleNamespace(enabled=True,structured=lambda *a:(_ for _ in ()).throw(AssertionError('Complete intake must not ask unrelated salary questions')))
    message='我要在南區設廠 招募品管員20位'
    plan=plan_request(ai,[{'role':'user','content':'2位前端工程師、2位全端工程師，兩個職位各5萬'},{'role':'user','content':message}])
    assert plan['action']=='draft' and plan['brief']==message
    assert plan['salary_turns']==[message]

def test_missing_local_salary_samples_continue_to_cited_city_search(monkeypatch):
    import recruitment.taiwan_salary as salary
    monkeypatch.setattr(salary,'salary_answer',lambda query:None)
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only')
    monkeypatch.setenv('LLM_MODE','auto')
    def handle(request):
        import json
        payload=json.loads(request.content)
        question=payload['messages'][-1]['content']
        assert '新社區前端工程師薪資' in question
        assert '臺北' in question and '新竹' in question
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'以臺北同職位薪資調查作為參考，與新社區分開標示。','annotations':[{'url_citation':{'title':'公開薪資調查','url':'https://www.mol.gov.tw/salary'}}]}}]})
    result=search_answer(RecruitmentAI(transport=httpx.MockTransport(handle)),'新社區前端工程師薪資')
    assert result['web_search_used'] is True
    assert result['sources'] and '臺北' in result['message']

def test_salary_and_duties_are_both_answered_without_publishing(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('recruitment.taiwan_salary.salary_answer',lambda query:{'message':'西屯區品檢員月薪參考38,000～57,500元。','sources':[{'title':'台灣就業通','url':'https://data.gov.tw/dataset/44062'}],'salary_reference':{'salary_min':38000,'salary_max':57500}})
    answer=search_answer(SimpleNamespace(enabled=False),'現在品管人員的薪資行情與工作內容？')
    assert '38,000～57,500' in answer['message']
    assert '工作內容' in answer['message'] and '異常' in answer['message']
    assert answer['answered_topics']==['duties','salary']
    assert any('onetonline.org' in s['url'] for s in answer['sources'])
    assert answer['salary_reference']['salary_min']==38000


def test_salary_only_does_not_add_unsolicited_duties(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('recruitment.taiwan_salary.salary_answer',lambda query:{'message':'薪資參考','sources':[]})
    answer=search_answer(SimpleNamespace(enabled=False),'品管人員薪資？')
    assert answer['message']=='薪資參考'
    assert answer['answered_topics']==['salary']


def test_duties_and_skills_question_does_not_call_salary_source(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('recruitment.taiwan_salary.salary_answer',lambda query:(_ for _ in ()).throw(AssertionError('salary not requested')))
    answer=search_answer(SimpleNamespace(enabled=False),'品管人員的工作內容與必要技能？')
    assert answer['answered_topics']==['duties','skills']
    assert '必要技能' in answer['message'] and '工作內容' in answer['message']


def test_planner_cannot_drop_original_requested_duties(c,monkeypatch):
    import recruitment.backend.main as module
    h=account(c);queries=[]
    monkeypatch.setattr(module,'plan_request',lambda *a:{'action':'search','query':'品管人員薪資'})
    monkeypatch.setattr(module,'search_answer',lambda ai,q:queries.append(q) or {'message':'完整回答','sources':[]})
    response=c.post('/assistant',headers=h,json={'message':'品管人員薪資與工作內容，還有福利？'})
    assert response.status_code==200
    assert '工作內容' in queries[0] and '福利' in queries[0]
    assert c.get('/batches',headers=h).json()==[]
