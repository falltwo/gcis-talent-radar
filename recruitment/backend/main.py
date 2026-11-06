import hashlib
import hmac
import os
import secrets
import json
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, Request, Query
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, select, update, event, delete
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from .models import *
from .schemas import Register, Login, Message, AssistantMessage, TemplateIn, ReferenceIn, ItemEdit, ExecutionRequest
from .ai import RecruitmentAI
from .ai import AIError
from .assistant import plan_request, search_answer, preserve_question_topics, pending_intake
from . import memory as context_memory
from .workflow import ConversationWorkflow

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / '.env', encoding='utf-8-sig')
def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + digest

def serialize(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}

def create_app(database_url=None):
    url = database_url or os.getenv('RECRUITMENT_DATABASE_URL') or ('sqlite:///' + (PROJECT_ROOT / 'database' / 'recruitment.sqlite3').as_posix())
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 15} if url.startswith('sqlite') else {}, pool_pre_ping=True)
    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def foreign_keys(dbapi, _): dbapi.execute('PRAGMA foreign_keys=ON')
    factory = sessionmaker(engine, expire_on_commit=False)
    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(engine)
        yield
        app.state.workflow.close()
        engine.dispose()
    app = FastAPI(title='AI 智慧招募 MVP', version='0.1.0', lifespan=lifespan)
    app.state.ai = RecruitmentAI()
    app.state.engine = engine
    app.state.session_factory = factory
    database=engine.url.database
    workflow_path=os.getenv('RECRUITMENT_WORKFLOW_DB')
    if not workflow_path:
        if engine.dialect.name=='sqlite':workflow_path=database+'.workflow.sqlite3' if database and database!=':memory:' else ':memory:'
        else:workflow_path=PROJECT_ROOT/'database'/'recruitment-workflow.sqlite3'
    app.state.workflow=ConversationWorkflow(workflow_path)
    workflow_namespace=hashlib.sha256(str(engine.url).encode()).hexdigest()[:16]
    def db():
        with factory() as session:
            try: yield session
            except Exception:
                session.rollback()
                raise
    bearer = HTTPBearer()
    def current(credentials: HTTPAuthorizationCredentials = Depends(bearer), s: Session = Depends(db)):
        digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        token = s.get(AccessToken, digest)
        if not token or token.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
            raise HTTPException(401, '登入已失效')
        user = s.get(User, token.user_id)
        if not user or user.role != 'hr': raise HTTPException(403, '需要 HR 權限')
        return user
    def audit(s, u, action, entity_id=None, detail=None):
        s.add(AuditLog(company_id=u.company_id, user_id=u.id, action=action, entity_id=entity_id, detail=detail or {}))
    def batch(s, u, bid, mutate=False):
        if mutate:
            # Atomic conditional write serializes mutations on SQLite and PostgreSQL.
            result = s.execute(update(RecruitmentBatch).where(RecruitmentBatch.id==bid, RecruitmentBatch.company_id==u.company_id, RecruitmentBatch.status!='published').values(status=RecruitmentBatch.status))
            if result.rowcount != 1:
                existing = s.scalar(select(RecruitmentBatch).where(RecruitmentBatch.id==bid, RecruitmentBatch.company_id==u.company_id))
                raise HTTPException(409 if existing else 404, '批次已刊登或不存在')
        b = s.scalar(select(RecruitmentBatch).where(RecruitmentBatch.id==bid, RecruitmentBatch.company_id==u.company_id).execution_options(populate_existing=True))
        if not b: raise HTTPException(404, '找不到批次')
        return b
    def items(s, bid): return s.scalars(select(RecruitmentBatchItem).where(RecruitmentBatchItem.batch_id==bid).order_by(RecruitmentBatchItem.id)).all()
    def missing(i):
        fields = [f for f in ['description','requirements','location','salary_min','salary_max'] if not getattr(i, f)]
        if not i.salary_confirmed: fields.append('salary_confirmation')
        return fields
    def view(s,b):
        return {**serialize(b), 'items': [{**serialize(i), 'missing_fields': missing(i)} for i in items(s,b.id)]}
    def enrich(s,u,data):
        t = s.scalar(select(JobTemplate).where(JobTemplate.company_id==u.company_id, JobTemplate.title==data['title']))
        if t:
            for f in ['description','requirements','location']: data.setdefault(f,getattr(t,f))
        if 'salary_min' not in data:
            r = s.scalar(select(SalaryTemplate).where(SalaryTemplate.company_id==u.company_id, SalaryTemplate.job_title==data['title']))
            source = t if t and t.salary_min is not None else r
            if source:
                data.update({f:getattr(source,f) for f in ['salary_min','salary_max','salary_type','currency']})
                data.update(salary_source='company_template' if source is t else 'salary_reference', salary_provenance=f'job_templates:{t.id}' if source is t else f'salary_templates:{r.id}; {r.data_source}', salary_confirmed=False)
        return data
    @app.get('/health')
    def health(): return {'status':'ok','parser':'openrouter' if app.state.ai.enabled else 'rules','llm_enabled':app.state.ai.enabled}
    @app.post('/auth/demo')
    def demo_session(request:Request,s:Session=Depends(db)):
        # Password-free access is explicitly limited to the local demo tenant.
        if os.getenv('RECRUITMENT_DEMO_ENABLED')!='1': raise HTTPException(404,'本機示範模式未啟用')
        if not request.client or request.client.host not in {'127.0.0.1','::1','testclient'} or request.url.hostname not in {'127.0.0.1','localhost','::1','testserver'}:
            raise HTTPException(403,'示範工作階段僅限本機使用')
        if request.headers.get('origin') and request.headers['origin']!=f'{request.url.scheme}://{request.url.netloc}':
            raise HTTPException(403,'不允許跨站建立工作階段')
        email='local-demo@recruitment.invalid'
        u=s.scalar(select(User).where(User.email==email))
        if not u:
            c=Company(company_name='本機示範公司');s.add(c);s.flush()
            u=User(company_id=c.id,name='示範HR',email=email,password_hash=password_hash(secrets.token_urlsafe(48)))
            s.add(u)
            try: s.commit()
            except IntegrityError:
                s.rollback();u=s.scalar(select(User).where(User.email==email))
                if not u: raise HTTPException(503,'建立示範工作階段失敗，請重試')
        raw=secrets.token_urlsafe(32)
        s.add(AccessToken(digest=hashlib.sha256(raw.encode()).hexdigest(),user_id=u.id,expires_at=now()+timedelta(hours=8)))
        audit(s,u,'demo_session');s.commit()
        return {'access_token':raw,'company_name':'本機示範公司','token_type':'bearer','expires_in':28800}
    @app.post('/auth/register', status_code=201)
    def register(body:Register,s:Session=Depends(db)):
        if body.email.lower()=='local-demo@recruitment.invalid': raise HTTPException(422,'此信箱保留給本機示範模式')
        if os.getenv('ALLOW_REGISTRATION','true').lower() != 'true': raise HTTPException(403,'註冊已停用')
        c = Company(company_name=body.company_name); s.add(c); s.flush()
        u = User(company_id=c.id,name=body.name,email=body.email.lower(),password_hash=password_hash(body.password)); s.add(u)
        try: s.flush(); audit(s,u,'register',u.id); s.commit()
        except IntegrityError: s.rollback(); raise HTTPException(409,'Email 已使用')
        return {'id':u.id,'company_id':c.id,'email':u.email}
    @app.post('/auth/login')
    def login(body:Login,s:Session=Depends(db)):
        u = s.scalar(select(User).where(User.email==body.email.lower()))
        stored = u.password_hash if u else password_hash('dummy-password')
        if not hmac.compare_digest(password_hash(body.password,stored.split(':')[0]),stored) or not u: raise HTTPException(401,'帳號或密碼錯誤')
        raw = secrets.token_urlsafe(32)
        s.add(AccessToken(digest=hashlib.sha256(raw.encode()).hexdigest(),user_id=u.id,expires_at=now()+timedelta(hours=8)))
        audit(s,u,'login'); s.commit()
        return {'access_token':raw,'token_type':'bearer','expires_in':28800}
    @app.get('/auth/me')
    def me(u=Depends(current),s:Session=Depends(db)):
        company=s.get(Company,u.company_id)
        return {'id':u.id,'company_id':u.company_id,'name':u.name,'company_name':company.company_name}
    @app.post('/auth/logout',status_code=204)
    def logout(creds:HTTPAuthorizationCredentials=Depends(bearer),u=Depends(current),s:Session=Depends(db)):
        s.delete(s.get(AccessToken,hashlib.sha256(creds.credentials.encode()).hexdigest())); audit(s,u,'logout'); s.commit()
    @app.post('/job-templates',status_code=201)
    def add_template(body:TemplateIn,u=Depends(current),s:Session=Depends(db)):
        row=JobTemplate(company_id=u.company_id,**body.model_dump()); s.add(row)
        try: s.flush(); audit(s,u,'create_job_template',row.id); s.commit()
        except IntegrityError: s.rollback(); raise HTTPException(409,'職稱範本已存在')
        return serialize(row)
    @app.post('/salary-templates',status_code=201)
    def add_salary(body:ReferenceIn,u=Depends(current),s:Session=Depends(db)):
        row=SalaryTemplate(company_id=u.company_id,**body.model_dump()); s.add(row)
        try: s.flush(); audit(s,u,'create_salary_reference',row.id); s.commit()
        except IntegrityError: s.rollback(); raise HTTPException(409,'薪資參考已存在')
        return serialize(row)
    @app.get('/job-templates')
    def templates(u=Depends(current),s:Session=Depends(db)):
        return [serialize(x) for x in s.scalars(select(JobTemplate).where(JobTemplate.company_id==u.company_id))]
    @app.get('/salary-templates')
    def salaries(u=Depends(current),s:Session=Depends(db)):
        return [serialize(x) for x in s.scalars(select(SalaryTemplate).where(SalaryTemplate.company_id==u.company_id))]
    def create_batch(body,u,s,salary_turns=None,parsed_override=None,commit=True):
        try:
            if parsed_override is None:
                parsed, ai_info = app.state.ai.extract(body.message,**({'salary_turns':salary_turns} if salary_turns is not None else {}))
            else:
                fields={'title','quantity','description','requirements','location','salary_min','salary_max','salary_type','currency','salary_source','salary_provenance','salary_confirmed'}
                parsed=[{k:v for k,v in row.items() if k in fields} for row in parsed_override]
                ai_info=app.state.ai.metadata('rules','short_term_context')
        except ValueError as e: raise HTTPException(422,str(e))
        b=RecruitmentBatch(company_id=u.company_id,created_by=u.id,original_text=body.message); s.add(b); s.flush()
        for data in parsed: s.add(RecruitmentBatchItem(batch_id=b.id,**enrich(s,u,data)))
        s.add(ChatLog(company_id=u.company_id,user_id=u.id,role='user',content=body.message))
        s.add(ChatLog(company_id=u.company_id,user_id=u.id,role='assistant',content=f'已建立草稿批次 {b.id}，請補齊缺漏欄位並確認。'))
        audit(s,u,'create_batch',b.id,{'ai':ai_info}); s.commit() if commit else s.flush(); return {**view(s,b),'ai':ai_info}
    @app.post('/batches',status_code=201)
    def draft(body:Message,u=Depends(current),s:Session=Depends(db)):
        return create_batch(body,u,s)
    @app.get('/batches')
    def list_batches(u=Depends(current),s:Session=Depends(db)):
        return [serialize(b) for b in s.scalars(select(RecruitmentBatch).where(RecruitmentBatch.company_id==u.company_id))]
    def assistant_turn(body,u,s,state,memory):
        from agent.prompt_guard import inspect_hiring_prompt
        now=datetime.now(timezone.utc)
        recent=state.get('messages',[])
        pinned=([context_memory.brief_for(state)] if state.get('items') else state.get('pending_requests',[]))
        messages=[{'role':'user','content':text} for text in pinned if not any(m['role']=='user' and m['content']==text for m in recent)]+recent+[{'role':'user','content':body.message}]
        cleared=bool(context_memory.CLEAR.fullmatch(body.message.strip()))
        rejected=inspect_hiring_prompt(body.message)['decision']=='REJECT'
        if cleared:
            state={};result={'kind':'clarify','message':'已清除這段對話的短期記憶。請提供新的招募需求。','sources':[]}
        elif rejected:
            result={'kind':'clarify','message':'請以工作技能、職責與必要經驗設定條件，不使用年齡、性別等個人特徵篩選。','sources':[]}
        else:
            try:
                patched=context_memory.patch(state,body.message)
                if patched and patched['kind']=='patch':
                    plan={'action':'draft','brief':context_memory.brief_for(patched['state']),'items':patched['state']['items']}
                elif patched:
                    if patched.get('pending_salary'):state['pending_salary']=patched['pending_salary']
                    plan={'action':'ack' if patched['kind']=='ack' else 'clarify','reply':patched['message']}
                else:plan=plan_request(app.state.ai,messages)
            except (AIError,ValueError):
                raise HTTPException(503,'助理暫時無法判斷需求，請稍後重試；未建立職缺。') from None
            if plan['action']=='draft':
                if inspect_hiring_prompt(plan['brief'])['decision']=='REJECT':
                    raise HTTPException(422,'請移除個人特徵篩選條件，改以職責與技能建立職缺')
                if len(plan['brief'])>4000:raise HTTPException(422,'這次需求過長，請分批提供職稱與人數')
                try:
                    created=create_batch(Message(message=plan['brief']),u,s,plan.get('salary_turns'),plan.get('items'),commit=False)
                    state=context_memory.snapshot(created,state)
                    state["batch_id"]=created["id"]
                    result={'kind':'batch','message':'已依你提供的條件建立企業職缺草稿；請審核後再刊登。','batch':created,'sources':[]}
                except HTTPException as exc:
                    if exc.status_code!=422:raise
                    result={'kind':'clarify','message':str(exc.detail),'sources':[]}
            elif plan['action']=='search':
                from recruitment.taiwan_salary import location_in
                query=preserve_question_topics(plan['query'],body.message)
                if not location_in(query):query+=' 臺中市（整體，不限行政區）'
                result={'kind':'answer',**search_answer(app.state.ai,query)}
            else:result={'kind':'ack' if plan['action']=='ack' else 'clarify','message':plan['reply'] or '請告訴我職稱與招募人數，或直接詢問職缺、薪資相關問題。','sources':[]}
        s.add(ChatLog(company_id=u.company_id,user_id=u.id,role='user',content=body.message))
        s.add(ChatLog(company_id=u.company_id,user_id=u.id,role='assistant',content=result['message']))
        if not cleared and not rejected:
            if result['kind']=='clarify' and not state.get('items') and not context_memory.is_information_request(body.message):
                state['pending_requests']=(state.get('pending_requests',[])+[body.message])[-6:]
                pending=plan.get('pending_question') or pending_intake(body.message)
                if pending:state['pending_question']=pending
            state['messages']=(state.get('messages',[])+[{'role':'user','content':body.message},{'role':'assistant','content':result['message'][:2000]}])[-10:]
        memory.state=state;memory.expires_at=now+timedelta(seconds=context_memory.TTL_SECONDS)
        audit(s,u,'assistant_turn',detail={'kind':result['kind'],'sources':len(result.get('sources',[]))});s.flush()
        return state,{**result,'context':{'expires_in':context_memory.TTL_SECONDS,'remembered_roles':[row['title'] for row in state.get('items',[])],'pending_question':state.get('pending_question'),'engine':'langgraph'}}
    @app.post('/assistant')
    def assistant(body:AssistantMessage,u=Depends(current),s:Session=Depends(db)):
        owner=(AssistantMemory.company_id==u.company_id,AssistantMemory.user_id==u.id,AssistantMemory.conversation_id==body.conversation_id)
        def receipt(request_id):
            return s.scalar(select(AssistantTurn).where(AssistantTurn.company_id==u.company_id,AssistantTurn.user_id==u.id,AssistantTurn.conversation_id==body.conversation_id,AssistantTurn.request_id==request_id))
        def fingerprint(event):
            return hashlib.sha256(json.dumps([event['message'],event['district']],ensure_ascii=False).encode()).hexdigest()
        event={'message':body.message,'district':body.district,'request_id':body.request_id}
        previous=receipt(body.request_id)
        if previous:
            if previous.fingerprint!=fingerprint(event):raise HTTPException(409,'這個請求編號已用於不同內容，未重複執行。')
            return previous.result
        def handle(state,event):
            memory=s.scalar(select(AssistantMemory).where(*owner))
            previous=receipt(event['request_id'])
            if previous:
                if previous.fingerprint!=fingerprint(event):
                    return {'memory':dict(memory.state) if memory else state,'result':{'_http_error':409,'detail':'這個請求編號已用於不同內容，未重複執行。'}}
                return {'memory':dict(memory.state) if memory else state,'result':previous.result}
            now=datetime.now(timezone.utc)
            if memory is None:
                memory=AssistantMemory(company_id=u.company_id,user_id=u.id,conversation_id=body.conversation_id,state={},expires_at=now+timedelta(seconds=context_memory.TTL_SECONDS));s.add(memory)
            elif memory.expires_at.replace(tzinfo=timezone.utc)<=now:
                state['messages']=[]
            try:
                turn_body=AssistantMessage(**event,conversation_id=body.conversation_id)
                state,result=assistant_turn(turn_body,u,s,state,memory)
                result=jsonable_encoder(result)
                memory.state=jsonable_encoder(state)
                s.add(AssistantTurn(company_id=u.company_id,user_id=u.id,conversation_id=body.conversation_id,request_id=event['request_id'],fingerprint=fingerprint(event),result=result))
                s.commit()
                return {'memory':memory.state,'result':result}
            except HTTPException as exc:
                s.rollback()
                return {'memory':state,'result':{'_http_error':exc.status_code,'detail':exc.detail}}
        initial=s.scalar(select(AssistantMemory).where(*owner))
        initial_memory=dict(initial.state) if initial else {}
        thread_id=f'{workflow_namespace}:{u.company_id}:{u.id}:{body.conversation_id}'
        completed=app.state.workflow.run(thread_id,event,handle,initial_memory)
        result=completed['result']
        if '_http_error' in result:raise HTTPException(result['_http_error'],result['detail'])
        return result

    @app.get('/assistant/task')
    def assistant_task(conversation_id:str=Query(default='legacy',pattern=r'^[A-Za-z0-9_-]{1,80}$'),u=Depends(current),s:Session=Depends(db)):
        memory=s.scalar(select(AssistantMemory).where(AssistantMemory.company_id==u.company_id,AssistantMemory.user_id==u.id,AssistantMemory.conversation_id==conversation_id))
        state=memory.state if memory else {}
        return {'engine':'langgraph','conversation_id':conversation_id,'items':state.get('items',[]),'batch_id':state.get('batch_id'),'pending_question':state.get('pending_question')}

    @app.get('/salary-reference')
    def salary_reference(role:str=Query(min_length=1,max_length=120),district:str=Query(default='',max_length=80),u=Depends(current)):
        from recruitment.taiwan_salary import get_reference
        return get_reference(role,district)
    @app.post('/execution/prepare')
    def execution(body:ExecutionRequest,u=Depends(current),s:Session=Depends(db)):
        from .execution import prepare_execution
        b=batch(s,u,body.batch_id)
        if b.status=='published':raise HTTPException(409,'這次職缺已刊登，請提出新的招募需求。')
        company=s.get(Company,u.company_id)
        try:prepared=prepare_execution(app.state.ai,view(s,b),company.company_name,body.district)
        except (ValueError,AIError) as exc:raise HTTPException(422,str(exc) if isinstance(exc,ValueError) else 'AI擬定內容暫時未完成，請重試。') from None
        return {'jobs':prepared,'requires_final_confirmation':True}
    @app.get('/batches/{bid}')
    def get_batch(bid:int,u=Depends(current),s:Session=Depends(db)): return view(s,batch(s,u,bid))
    @app.put('/batches/{bid}/items/{iid}')
    def edit(bid:int,iid:int,body:ItemEdit,u=Depends(current),s:Session=Depends(db)):
        b=batch(s,u,bid,True)
        i=s.scalar(select(RecruitmentBatchItem).where(RecruitmentBatchItem.batch_id==bid,RecruitmentBatchItem.id==iid))
        if not i: raise HTTPException(404,'找不到項目')
        data=body.model_dump(exclude={'confirm_salary'})
        salary_changed=any(data[f]!=getattr(i,f) for f in ['salary_min','salary_max','salary_type','currency'])
        before=serialize(i)
        if salary_changed:
            i.salary_source='hr_explicit' if body.salary_min is not None else 'missing'
            i.salary_provenance=f'HR {u.id} 透過編輯 API 指定'
            i.salary_confirmed=body.salary_min is not None
        elif body.confirm_salary and i.salary_min is not None: i.salary_confirmed=True
        for k,v in data.items(): setattr(i,k,v)
        b.status='draft'
        # Store business-field changes, avoiding datetime JSON serialization.
        audit(s,u,'edit_item',i.id,{'before':{k:before[k] for k in data},'after':data})
        s.commit(); return view(s,b)
    @app.post('/batches/{bid}/confirm')
    def confirm(bid:int,u=Depends(current),s:Session=Depends(db)):
        b=batch(s,u,bid,True); rows=items(s,bid)
        errors={i.id:missing(i) for i in rows if missing(i)}
        if not rows or errors: raise HTTPException(422,{'message':'請先補齊並確認薪資','items':errors})
        b.status='confirmed'; audit(s,u,'confirm_batch',bid); s.commit(); return view(s,b)
    @app.post('/batches/{bid}/publish')
    def publish(bid:int,u=Depends(current),s:Session=Depends(db)):
        b=batch(s,u,bid,True)
        if b.status!='confirmed': raise HTTPException(409,'請先由 HR 確認批次')
        rows=items(s,bid)
        if not rows or any(missing(i) for i in rows): raise HTTPException(422,'批次資料不完整')
        postings=[]
        for i in rows:
            data={k:getattr(i,k) for k in ['title','quantity','description','requirements','location','salary_min','salary_max','salary_type','currency','salary_source','salary_provenance']}
            p=JobPosting(company_id=u.company_id,batch_item_id=i.id,**data); s.add(p); postings.append(p)
        b.status='published'; audit(s,u,'publish_batch',bid,{'item_count':len(rows)})
        # All postings, batch status and audit record share this single commit.
        s.commit(); return {'batch_id':bid,'status':b.status,'postings':[serialize(p) for p in postings]}
    @app.get('/job-postings')
    def jobs(u=Depends(current),s:Session=Depends(db)):
        return [serialize(p) for p in s.scalars(select(JobPosting).where(JobPosting.company_id==u.company_id))]
    @app.post('/chat')
    def chat(body:Message,u=Depends(current),s:Session=Depends(db)):
        query=body.message
        # Only this tenant's titles are provided to the model; no salaries, user accounts,
        # chat histories or database credentials leave the application.
        company_rows=s.scalars(select(JobTemplate).where(JobTemplate.company_id==u.company_id)).all()
        salary_rows=s.scalars(select(SalaryTemplate).where(SalaryTemplate.company_id==u.company_id)).all()
        posted_rows=s.scalars(select(JobPosting).where(JobPosting.company_id==u.company_id)).all()
        available=sorted({r.title for r in company_rows+posted_rows}|{r.job_title for r in salary_rows})
        if len(available)>500:
            plan=None; ai_info=app.state.ai.metadata('rules','catalog_too_large')
        else:
            plan,ai_info=app.state.ai.query(query,available)
        salary_query=plan.intent=='salary' if plan else any(w in query for w in ['薪資','薪水','月薪','年薪','時薪'])
        def matches(title):
            if plan: return not plan.titles or title in plan.titles
            return title in query or any(w in query for w in ['所有','全部']) or (not salary_query and '職缺' in query)
        if salary_query:
            refs=[serialize(r) for r in salary_rows if matches(r.job_title)]
            company=[serialize(r) for r in company_rows if matches(r.title)]
            posted=[serialize(r) for r in posted_rows if matches(r.title)]
            reply={'message':'僅列出公司已儲存的資料；範本與參考薪資需 HR 確認，不代表市場統計。' if refs or company or posted else '查無資料，請 HR 提供薪資或具來源的參考資料。','salary_references':refs,'company_templates':company,'job_postings':posted}
        else:
            posted=[serialize(r) for r in posted_rows if matches(r.title)]
            reply={'message':'以下為已刊登職缺。建立草稿請使用 /batches。','job_postings':posted}
        import json
        for role,content in [('user',query),('assistant',json.dumps(reply,ensure_ascii=False,default=str))]: s.add(ChatLog(company_id=u.company_id,user_id=u.id,role=role,content=content))
        audit(s,u,'chat_query',detail={'ai':ai_info}); s.commit(); return {'parser':ai_info['mode'],'ai':ai_info,**reply}
    @app.get('/chat-logs')
    def chats(limit:int=100,u=Depends(current),s:Session=Depends(db)):
        return [serialize(r) for r in s.scalars(select(ChatLog).where(ChatLog.company_id==u.company_id).order_by(ChatLog.id.desc()).limit(max(1,min(limit,200))))]
    @app.get('/audit-logs')
    def audits(limit:int=100,u=Depends(current),s:Session=Depends(db)):
        return [serialize(r) for r in s.scalars(select(AuditLog).where(AuditLog.company_id==u.company_id).order_by(AuditLog.id.desc()).limit(max(1,min(limit,200))))]
    return app
