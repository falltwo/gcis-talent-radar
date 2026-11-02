'use strict';
(async () => {
  if (location.hash !== '#agent') return;
  const portal = window.MockPortal;
  await portal.ready;
  const style = document.createElement('style');
  style.textContent = '.agent-hud{position:sticky;top:0;z-index:20;background:#103a34;color:#f0faf4;padding:12px 24px;display:flex;justify-content:space-between;gap:14px;align-items:center;box-shadow:0 5px 15px #102f2420}.agent-hud strong{font-size:14px}.agent-hud p{font-size:12px;color:#c6e1d3;margin:3px 0 0}.agent-hud button,.agent-hud a{font-size:12px;min-height:34px;padding:6px 12px;white-space:nowrap}.agent-hud a{color:#e1f2e8}.agent-hud .controls{display:flex;gap:8px;align-items:center}.agent-filling{outline:3px solid #d47d28!important;outline-offset:3px;background:#fff9ec!important}.agent-filled{border-color:#568b69!important}.agent-log{font-size:11px;color:#c6e1d3}.agent-hud details{font-size:11px;margin-top:4px}.agent-hud summary{cursor:pointer}.agent-hud ol{margin:6px 0;padding-left:18px;max-height:110px;overflow:auto}@media(max-width:720px){.agent-hud{padding:11px 15px;align-items:start;flex-wrap:wrap}.agent-hud .controls{width:100%;flex-wrap:wrap}}';
  document.head.append(style);
  const hud = document.createElement('aside');
  hud.className = 'agent-hud';
  hud.setAttribute('aria-label','Agent 自動填表狀態');
  hud.innerHTML = '<div><strong id="agent-title" role="status" aria-live="polite">Agent 正在開啟企業刊登頁</strong><p id="agent-copy">只操作此模擬網站，不會連線至 104。</p><details><summary>查看操作紀錄</summary><ol id="agent-log"></ol></details></div><div class="controls"><button class="secondary" id="agent-pause">暫停</button><button class="secondary" id="agent-stop">停止操作</button><a href="/recruitment-agent">回 HR 工作台</a></div>';
  document.querySelector('.demo-banner').after(hud);
  let run, paused = false, stopped = false, publishing = false;
  const title = document.getElementById('agent-title'), copy = document.getElementById('agent-copy');
  const pauseButton = document.getElementById('agent-pause'), stopButton = document.getElementById('agent-stop');
  const sleep = ms => new Promise(resolve=>setTimeout(resolve,ms));
  async function request(path,body,method='POST') {
    const response=await fetch('/api/mock104/agent/'+path,{method,credentials:'same-origin',cache:'no-store',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
    const data=await response.json();
    if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'操作未完成，請回工作台重新確認。');
    return data;
  }
  function message(text,detail) {
    title.textContent=text;if(detail)copy.textContent=detail;
    const li=document.createElement('li');li.textContent=new Date().toLocaleTimeString('zh-TW',{hour12:false})+'　'+text;
    document.getElementById('agent-log').prepend(li);
  }
  async function checkpoint() { while(paused&&!stopped)await sleep(80);if(stopped)throw new Error('已停止操作。'); }
  pauseButton.addEventListener('click',()=>{paused=!paused;pauseButton.textContent=paused?'繼續操作':'暫停';title.textContent=paused?'Agent 已暫停，尚未繼續填寫':'Agent 繼續填寫';});
  stopButton.addEventListener('click',async()=>{if(!run||publishing)return;stopped=true;try{run=await request('cancel',{run_id:run.run_id});message('Agent 已停止','不會再送出刊登。可回工作台重新確認需求。');}catch(error){message('停止狀態未確認',error.message);}pauseButton.disabled=true;stopButton.disabled=true;document.querySelectorAll('[data-agent-action]').forEach(b=>b.disabled=true);});
  async function fill(name,value,label) {
    await checkpoint();
    const field=document.forms['job-form'].elements.namedItem(name);
    if(!field)throw new Error('找不到網站欄位：'+label+'，已停止操作。');
    message('正在填寫：'+label,'將 HR 已核准的內容填入企業刊登表單。');
    field.scrollIntoView({block:'center',behavior:run.typing_speed==='FAST'?'instant':'smooth'});
    field.classList.add('agent-filling');field.focus();
    const text=Array.isArray(value)?value.join('、'):String(value??'');
    if(field.tagName==='SELECT'){
      if(![...field.options].some(o=>o.value===text)){const option=document.createElement('option');option.value=text;option.textContent=text;field.append(option);}field.value=text;
      await sleep(run.typing_speed==='FAST'?35:250);
    }else if(field.type==='number') {field.value=text;await sleep(run.typing_speed==='FAST'?35:220);}
    else{field.value='';const chars=Array.from(text),chunk=run.typing_speed==='FAST'?24:Math.max(2,Math.ceil(chars.length/24));for(let i=0;i<chars.length;i+=chunk){await checkpoint();field.value+=chars.slice(i,i+chunk).join('');field.dispatchEvent(new Event('input',{bubbles:true}));await sleep(run.typing_speed==='FAST'?4:22);}}
    field.dispatchEvent(new Event('input',{bubbles:true}));field.dispatchEvent(new Event('change',{bubbles:true}));
    field.classList.remove('agent-filling');field.classList.add('agent-filled');await sleep(run.typing_speed==='FAST'?35:180);
  }
  function decorate(event) {
    if(!run||run.job_id!==event.detail.id||event.detail.publicView||!['AWAITING_CONFIRMATION','READY_TO_PUBLISH'].includes(run.phase))return;
    const box=document.querySelector('#detail-view .review-box');if(!box)return;
    box.querySelectorAll('button[data-action=submit],button[data-action=edit]').forEach(b=>b.hidden=true);
    const scenario=box.querySelector('#scenario');if(scenario){scenario.value=run.scenario;scenario.disabled=true;}
    if(!box.querySelector('[data-agent-action=publish]')) {
      const button=document.createElement('button');button.className='primary';button.dataset.agentAction='publish';
      button.textContent=run.confirm_before_publish?'確認內容，讓 Agent 模擬刊登':'繼續 Agent 模擬刊登';
      button.addEventListener('click',()=>publish(true));box.prepend(button);
      const note=document.createElement('p');note.textContent='Agent 已填完並核對 HR 核准版本。此按鈕只會刊登到模擬工作網。';box.prepend(note);
    }
  }
  document.addEventListener('mockportal:detail',decorate);
  async function publish(humanConfirmation) {
    if(publishing||stopped)return;
    publishing=true;pauseButton.disabled=true;stopButton.disabled=true;
    document.querySelectorAll('[data-agent-action]').forEach(b=>b.disabled=true);
    try {
      message('Agent 正在送出模擬刊登','只送出到橙才模擬平台。');
      portal.ingest(await portal.request('jobs/'+run.job_id+'/submit',{scenario:run.scenario,agent_confirmation:humanConfirmation}));run.phase='SUBMITTED';
      portal.showDetail(run.job_id);
      portal.ingest(await portal.request('jobs/'+run.job_id+'/approve',{}));portal.showDetail(run.job_id);
      message('模擬平台處理中','正在等待本地模擬刊登結果。');await sleep(900);
      portal.ingest(await portal.request('jobs/'+run.job_id+'/complete',{}));portal.showDetail(run.job_id);
      run=await request('run',null,'GET');
      message(run.phase==='PUBLISHED'?'Agent 已完成模擬刊登':'模擬平台回傳失敗',run.phase==='PUBLISHED'?'職缺已出現在求職者預覽；未送至104。':'可在模擬平台查看失敗原因與重試選項。');
    } catch(error){message('刊登尚未完成',error.message);}
    finally {publishing=false;}
  }
  try {
    run=await request('run',null,'GET');
    if(run.phase!=='READY'){
      if(run.job_id){portal.showDetail(run.job_id);message(run.phase==='AWAITING_CONFIRMATION'?'Agent 已填完，等待 HR 第二次確認':'已恢復這次模擬工作的狀態','可在右側確認內容或查看刊登結果。');if(run.phase==='READY_TO_PUBLISH')await publish(false);}
      else message('上次填表流程尚未完成','請先停止操作，再回HR工作台重新確認，避免重複建立職缺。');
      pauseButton.disabled=true;return;
    }
    run=await request('claim',{run_id:run.run_id});
    const create=document.querySelector('#manage-view .heading [data-action=new]');create.click();
    await sleep(120);history.replaceState(null,'','#agent');message('已開啟企業刊登表單','現在開始填入職缺基本資訊。');
    for(const [key,label]of [['title','職缺名稱'],['company_name','公司名稱'],['employment_type','工作性質'],['district','工作地區'],['company_intro','公司簡介'],['description','工作內容']])await fill(key,run.job[key],label);
    await checkpoint();document.getElementById('next').click();
    if(portal.getStep()!==2)throw new Error('基本資訊未通過網站驗證，已停止。');
    message('已切換至工作條件頁','繼續填入薪資、班制與時間。');
    for(const[key,label]of [['salary_min','月薪下限'],['salary_max','月薪上限'],['schedule_system','班制'],['shift','班別'],['work_hours','上班時間'],['headcount','需求人數'],['min_experience_months','工作經驗'],['required_skills','必要技能'],['trainable_skills','可培訓技能']])await fill(key,run.job[key],label);
    await checkpoint();message('填表完成，正在儲存並核對','確認網站內容和HR核准版本完全一致。');document.getElementById('next').click();
    for(let i=0;i<200&&portal.isBusy();i++){await checkpoint();await sleep(50);}
    await checkpoint();const id=portal.selectedJob();if(!id)throw new Error(document.getElementById('error').textContent||'網站尚未完成儲存，已停止操作。');
    run=await request('filled',{run_id:run.run_id,job_id:id});portal.showDetail(id);
    pauseButton.disabled=true;window.scrollTo({top:0,behavior:'instant'});
    if(run.confirm_before_publish)message('Agent 已填完，等待 HR 第二次確認','請檢查網站上的實際刊登內容；確認後才會送出。');else await publish(false);
  } catch(error) {message(stopped?'Agent 已停止':'Agent 尚未完成',error.message);pauseButton.disabled=true;}
})();
