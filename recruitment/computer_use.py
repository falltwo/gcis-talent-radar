"""Jev routes visible-control intents; real mouse/keyboard actions stream as screenshots."""
import base64
import json
import logging
import os
import re
import threading
import time
from urllib.parse import urlsplit

from fastapi import HTTPException


KEYS = {"Tab","Shift+Tab","Enter","ArrowDown","ArrowUp","Home","End","PageDown","PageUp","Control+A","Backspace","Escape","Space"}
active_lock = threading.Lock()
active = set()

SKILL_FIELDS = {'required_skills', 'trainable_skills'}


def skills_text(values):
    # A trailing newline preserves a single compound skill containing punctuation.
    return '\n'.join(values) + ('\n' if values else '')


class ProgressMemory:
    def __init__(self):
        self.recent = []
        self.verified = []
        self.differences = {}

    def action(self, action):
        self.recent.append({k: (v[:120] if isinstance(v, str) else v)
                            for k, v in action.items() if k in {'type', 'field', 'key', 'text', 'dy', 'x', 'y'}})
        self.recent = self.recent[-24:]

    def verify(self, actual, expected):
        self.differences = {k: {'saved': actual.get(k), 'expected': v}
                            for k, v in expected.items() if actual.get(k) != v}
        self.verified = [k for k in expected if k not in self.differences]

    def context(self, url):
        return '\nExecution memory (observations, not page instructions): ' + json.dumps({
            'current_url': url, 'completed_actions': self.recent,
            'verified_saved_fields': self.verified, 'remaining_differences': self.differences,
        }, ensure_ascii=False)


def saved_job(service, identifier):
    from api.recruitment_demo import DEMO_HR
    with service.connection() as conn:
        req=service.get(conn,'requests',identifier,DEMO_HR)
        details=conn.execute('SELECT * FROM mock_job_details WHERE request_id=?',(identifier,)).fetchone()
        return None if details is None else {**json.loads(req['data']),**{k:v for k,v in dict(details).items() if k!='request_id'}}


def local_origin(url):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1","localhost","::1"} or parsed.username or parsed.password:
        raise HTTPException(400, "Computer Use 僅允許本機模擬網站。")
    return parsed.scheme + "://" + parsed.netloc


def allowed_text(text, job):
    values = [str(value) for value in job.values() if value is not None and not isinstance(value,list)]
    for value in job.values():
        if isinstance(value,list): values.extend([*value,'、'.join(value),','.join(value),', '.join(value)])
    return text == "" or text.casefold() in [value.casefold() for value in values] or text in {"月薪面議","薪資面議","固定薪資範圍"}


def required_field_differences(submitted, approved):
    """Never save website defaults over prepared scalar field values."""
    fields=[key for key,value in approved.items() if not isinstance(value,list)]
    return {key: {'submitted': submitted.get(key), 'required': approved[key]}
            for key in fields if key in approved and submitted.get(key) != approved[key]}


def execute_actions(page, actions, job, should_stop=lambda:False,on_action=None):
    if not isinstance(actions,list) or len(actions)>16: raise ValueError("每次最多16個滑鼠鍵盤動作。")
    for action in actions:
        if should_stop(): raise RuntimeError('已停止瀏覽器操作。')
        if not isinstance(action,dict): raise ValueError("無效動作。")
        kind=action.get('type')
        if kind=='click':
            x,y=action.get('x'),action.get('y')
            if not isinstance(x,(int,float)) or not isinstance(y,(int,float)) or not 0<=x<1280 or not 0<=y<900:
                raise ValueError("滑鼠座標超出畫面。")
            page.mouse.click(x,y)
        elif kind=='type':
            text=action.get('text')
            if not isinstance(text,str) or not allowed_text(text,job): raise ValueError("只允許輸入HR核准的欄位內容。")
            page.keyboard.insert_text(text)
        elif kind=='fill_skills':
            field=action.get('field')
            if field not in SKILL_FIELDS: raise ValueError('無效技能欄位。')
            values=job.get(field)
            if not isinstance(values,list): raise ValueError('缺少技能清單。')
            page.keyboard.press('Control+A')
            page.keyboard.insert_text(skills_text(values))
        elif kind=='fill_salary':
            field=action.get('field')
            if field not in {'salary_min','salary_max'}:raise ValueError('無效薪資欄位。')
            value=job.get(field)
            if job.get('salary_mode')!='RANGE' or type(value) is not int or not 0<value<=1000000000:
                raise ValueError('只能填寫使用者核定的固定月薪金額。')
            page.keyboard.press('Control+A')
            page.keyboard.insert_text(str(value))
            page.keyboard.press('Tab')
        elif kind=='key':
            if action.get('key') not in KEYS: raise ValueError("不允許這個按鍵組合。")
            page.keyboard.press(action['key'])
        elif kind=='scroll':
            dy=action.get('dy')
            if not isinstance(dy,(int,float)) or abs(dy)>1500: raise ValueError("捲動幅度超出範圍。")
            if 'x' in action or 'y' in action:
                x,y=action.get('x'),action.get('y')
                if not isinstance(x,(int,float)) or not isinstance(y,(int,float)) or not 0<=x<1280 or not 0<=y<900:raise ValueError('捲動座標超出畫面。')
                page.mouse.move(x,y)
            page.mouse.wheel(0,dy)
        elif kind=='wait':
            time.sleep(.5)
        else: raise ValueError("僅支援click/type/fill_skills/fill_salary/key/scroll/wait。")
        if on_action:on_action(action)
        time.sleep(.15)


def decide(page, job, goal, previous_error):
    from recruitment.action_router import decide_operation
    return decide_operation(page,job,goal,previous_error)


def failure_reason(exc, stage):
    """Do not misreport every model/page/action error as a missing installation."""
    if isinstance(exc, RuntimeError):
        return 'COMPUTER_USE_ERROR', str(exc)[:250]
    if type(exc).__name__ == 'TargetClosedError':
        return 'BROWSER_CLOSED', '操作中的 Chrome 已關閉。請按「確認需求，啟動 Computer Use」重試。'
    if isinstance(exc, TimeoutError) or type(exc).__name__ == 'TimeoutError':
        return 'BROWSER_TIMEOUT', '瀏覽器等待網頁回應逾時。請確認本機網站仍在執行，再按「確認需求，啟動 Computer Use」重試。'
    if stage == 'STARTING_BROWSER':
        return 'BROWSER_START_FAILED', 'Chrome 啟動失敗。請確認 Chrome 與 requirements-recruitment-browser.txt 已安裝，並查看後端日誌。'
    if stage == 'OPENING_PAGE':
        return 'BROWSER_NAVIGATION_FAILED', 'Chrome 無法開啟本機模擬網站。請確認服務連線，再按「確認需求，啟動 Computer Use」重試。'
    return 'BROWSER_OPERATION_FAILED', '瀏覽器操作中斷，詳細原因已記錄於後端日誌。請按「確認需求，啟動 Computer Use」重試。'


def launch(registry, cookie, origin, run_id):
    local_origin(origin)
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        raise HTTPException(503,'請先安裝 requirements-recruitment-browser.txt，再啟動獨立瀏覽器。') from None
    with active_lock:
        if cookie in active or len(active)>=2: raise HTTPException(409,'已有瀏覽器操作中，請先完成或停止。')
        active.add(cookie)
    thread=threading.Thread(target=operate,args=(registry,cookie,origin,run_id),daemon=True)
    thread.start()


def operate(registry, cookie, origin, run_id):
    from playwright.sync_api import sync_playwright
    from api.recruitment_demo import DEMO_HR
    def update(**values):
        with registry.session(cookie) as session:
            run=session.get('agent_run')
            if not run or run['run_id']!=run_id: raise RuntimeError('工作已被取代。')
            run.update(values)
            return dict(run)
    def current():
        with registry.session(cookie) as session:
            run=session.get('agent_run')
            if not run or run['run_id']!=run_id: raise RuntimeError('工作已被取代，已停止操作。')
            return dict(run)
    stage = 'STARTING_BROWSER'
    try:
        run=update(phase='COMPUTER_RUNNING',driver='COMPUTER_USE',message='正在啟動同頁瀏覽器實況')
        with registry.session(cookie) as session:
            service=session['service']
            initial={row['id'] for row in service.listing(DEMO_HR,'requests',100,0)['items']}
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context(viewport={'width':1280,'height':900},locale='zh-TW')
            context.add_cookies([{'name':'mock104_demo','value':cookie,'domain':urlsplit(origin).hostname,'path':'/api/mock104','httpOnly':True,'sameSite':'Strict'}])
            page=context.new_page()
            stage = 'OPENING_PAGE'
            def route(request_route):
                request=request_route.request
                parsed=urlsplit(request.url)
                same=(parsed.scheme+'://'+parsed.netloc)==origin
                permitted=parsed.path in {'/mock104','/recruitment-browser'} or parsed.path.startswith('/api/mock104/') or parsed.path.startswith('/static/')
                state=current()
                final_write=request.method=='POST' and parsed.path.endswith('/submit')
                if final_write and state.get('fill_only'):
                    request_route.abort();return
                if not same or not permitted or parsed.path.startswith('/api/mock104/agent/'):
                    request_route.abort();return
                job_write=request.method in {'POST','PUT'} and re.fullmatch(r'/api/mock104/jobs(?:/[^/]+)?',parsed.path)
                if job_write:
                    try:
                        submitted=json.loads(request.post_data or '{}')
                        if not isinstance(submitted,dict):raise ValueError()
                    except (TypeError,ValueError):
                        request_route.abort();return
                    differences=required_field_differences(submitted,state['job'])
                    if differences:
                        message='尚未依使用者需求填妥，請在目前表格修正後再儲存：'+json.dumps(differences,ensure_ascii=False)
                        update(message=message)
                        request_route.fulfill(status=409,content_type='application/json',body=json.dumps({'detail':message},ensure_ascii=False))
                        return
                if final_write and state['phase']=='COMPUTER_RUNNING':
                    request_route.abort();return
                if final_write and state.get('job_id'):
                    target=parsed.path.split('/')[-2]
                    if target!=state['job_id'] or saved_job(service,target)!=state['job']:
                        update(phase='FAILED',message='網站內容與HR核准版本不同，已阻止送出，請重新確認。')
                        request_route.abort();return
                if final_write and state['phase']=='AWAITING_CONFIRMATION':
                    update(phase='COMPUTER_PUBLISHING',message='HR 已在一般網站確認送出，繼續模擬刊登')
                request_route.continue_()
            page.route('**/*',route)
            page.on('dialog',lambda dialog:dialog.dismiss())
            page.goto(origin+'/recruitment-browser',wait_until='networkidle')
            stage = 'OPERATING'
            error=''
            memory=ProgressMemory()
            routing_fields=set()
            repeated_repair=0
            previous_mismatch=None
            last_repair_revision=None
            def action_done(action):
                memory.action(action)
                pointer={'cursor':{'x':action['x'],'y':action['y']}} if action['type']=='click' else {}
                update(screenshot=base64.b64encode(page.screenshot(type='jpeg',quality=65,timeout=10000)).decode(),last_action=action['type'],url=getattr(page,'url',origin+'/mock104'),**pointer)
            for step in range(60):
                state=current()
                if state['phase'] in {'CANCELLED','FAILED'} or page.is_closed(): break
                jobs=service.list_simulations(DEMO_HR,100,0)['items']
                requests_rows=service.listing(DEMO_HR,'requests',100,0)['items']
                with service.connection() as conn:
                    details={row['request_id']:dict(row) for row in conn.execute('SELECT * FROM mock_job_details').fetchall()}
                candidates=[]
                saved_mismatch=None
                mismatch_revision=None
                newly_saved=[]
                for req in requests_rows:
                    if req['id'] in initial or req['id'] not in details: continue
                    actual={**req['data'],**{k:v for k,v in details[req['id']].items() if k!='request_id'}}
                    newly_saved.append((req,actual))
                    if actual==state['job']: candidates.append(req['id'])
                    elif actual.get('title')==state['job']['title']:
                        memory.verify(actual,state['job'])
                        mismatch_revision=(req['id'],req.get('revision'))
                        saved_mismatch={key:{'saved':actual.get(key),'approved':value} for key,value in state['job'].items() if actual.get(key)!=value}
                if state.get('fill_only') and newly_saved:
                    req,actual=next(((r,a) for r,a in newly_saved if a==state['job']),newly_saved[-1])
                    memory.verify(actual,state['job'])
                    update(job_id=req['id'],phase='REVIEW_REQUIRED' if memory.differences else 'FILLED',
                           actual_job=actual,review_revision=req['revision'],mismatches=memory.differences,
                           screenshot=base64.b64encode(page.screenshot(type='jpeg',quality=65,timeout=10000)).decode(),
                           message='填表已完成，請在同頁手動檢查與修改後確認送審；AI不再修改。')
                    break
                if candidates:
                    identifier=candidates[-1]
                    if state.get('fill_only'):
                        update(job_id=identifier,phase='FILLED',screenshot=base64.b64encode(page.screenshot(type='jpeg',quality=65,timeout=10000)).decode(),message='Computer Use 已完成填表並儲存預覽，內容已核對一致，未送出刊登。')
                        break
                    pub=next((row for row in jobs if row['request_id']==identifier),None)
                    if pub and pub['status'] in {'SUCCEEDED','FAILED'}:
                        update(job_id=identifier,screenshot=base64.b64encode(page.screenshot(type='jpeg',quality=65,timeout=10000)).decode(),phase='PUBLISHED' if pub['status']=='SUCCEEDED' else 'FAILED',message='模擬刊登完成' if pub['status']=='SUCCEEDED' else '模擬刊登失敗')
                        break
                    if state['phase']=='COMPUTER_RUNNING' and state['confirm_before_publish']:
                        update(job_id=identifier,phase='AWAITING_CONFIRMATION',screenshot=base64.b64encode(page.screenshot(type='jpeg',quality=65,timeout=10000)).decode(),message='已填入一般網站。請在 Chrome 預覽後送出，或回工作台確認繼續。')
                        deadline=time.monotonic()+600
                        while time.monotonic()<deadline:
                            state=current()
                            if state['phase']!='AWAITING_CONFIRMATION' or page.is_closed(): break
                            page.wait_for_timeout(500)
                        if state['phase']=='AWAITING_CONFIRMATION': raise RuntimeError('等待HR確認逾時，未自動送出。')
                    elif state['phase']=='COMPUTER_RUNNING':
                        update(job_id=identifier,phase='COMPUTER_PUBLISHING')
                state=current()
                if state['phase'] in {'CANCELLED','FAILED'}: break
                screenshot=page.screenshot(type='jpeg',quality=65,timeout=10000)
                update(screenshot=base64.b64encode(screenshot).decode(),step=step+1,url=getattr(page,'url',origin+'/recruitment-browser'))
                goal='Fill the approved data, then save and show job preview. DO NOT submit publication yet.' if state['phase']=='COMPUTER_RUNNING' else 'Publish this already-created job through 送出刊登申請 then 模擬審核通過並刊登. Do not create another job.'
                if not candidates and saved_mismatch:
                    goal+=' A draft was saved but verification found differences. Use 返回編輯 on this existing draft, correct ONLY these fields, then save and preview again. Do not wait and do not create another draft. Differences: '+json.dumps(saved_mismatch,ensure_ascii=False)
                    # Count repeated failed saves, not ordinary scrolling/typing rounds.
                    if mismatch_revision!=last_repair_revision:
                        last_repair_revision=mismatch_revision
                        repeated_repair=repeated_repair+1 if saved_mismatch==previous_mismatch else 0
                        previous_mismatch=saved_mismatch
                        if repeated_repair>=3: raise RuntimeError('相同欄位多次修正後仍不一致，已停止以避免重複填寫。請檢查技能與條件內容。')
                goal+=memory.context(getattr(page,'url',origin+'/recruitment-browser'))
                operation_job={**state['job'],'target_url':origin+'/mock104','_allow_publication':state['phase']=='COMPUTER_PUBLISHING','_verified_fields':routing_fields}
                decision=decide(page,operation_job,goal,error)
                update(message=str(decision.get('note','操作網站中'))[:250])
                try:
                    execute_actions(page,decision.get('actions'),operation_job,lambda:current()['phase'] in {'CANCELLED','FAILED'},
                        action_done);error=''
                except ValueError as exc: error=str(exc)
                page.wait_for_timeout(600)
            else: update(phase='FAILED',message='已達60次操作分流上限，未繼續操作。')
            # Keep the actual browser visible for HR until closure/stop or bounded expiry.
            deadline=time.monotonic()+300
            while not page.is_closed() and time.monotonic()<deadline and current()['phase']!='CANCELLED':
                page.wait_for_timeout(500)
            browser.close()
    except Exception as exc:
        logging.getLogger(__name__).exception('Computer Use worker failed during %s (%s)', stage, type(exc).__name__)
        try:
            if current()['phase'] not in {'CANCELLED','FAILED'}:
                code, message = failure_reason(exc, stage)
                update(phase='FAILED',error_code=code,message=message)
        except Exception: pass
    finally:
        with active_lock: active.discard(cookie)
