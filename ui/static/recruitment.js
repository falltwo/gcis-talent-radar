/* Three-act FRONTEND DEMO. Scripted progress replaces future backend events. */
(()=>{
  'use strict';
  const $=id=>document.getElementById(id),workspace=document.querySelector('.radar-workspace');
  const flow=new RecruitmentFlow.PostingFlow(),reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const panel=document.createElement('section');panel.className='posting-workspace';panel.hidden=true;panel.dataset.act='brief';panel.setAttribute('aria-label','刊登召募展示工作台');
  panel.innerHTML=`<header class="posting-header"><div><h2>刊登召募</h2><p>交代需求，觀看補齊，最後只審核一次。</p></div><div><span class="posting-demo">前端模擬・未連接後端</span><button type="button" id="posting-exit">退出</button></div></header>
  <ol class="posting-steps" aria-label="刊登流程"><li data-step="brief"><b>1</b>提出需求</li><li data-step="working"><b>2</b>Agent 補齊與填表</li><li data-step="review"><b>3</b>人工審核並刊登</li></ol>
  <div class="posting-columns"><section class="posting-requirements" aria-label="任務需求與進度"><div class="posting-left-heading" id="posting-left-heading">你的需求</div>
    <div id="posting-intake"><h3>你想找什麼樣的人？</h3><p class="posting-help">先給職稱與人數，其他內容交給展示流程補成草稿。</p>
      <label for="posting-brief">用一句話交代需求<textarea id="posting-brief" rows="3" maxlength="500" placeholder="例如：我想招 5 位 CNC 技術員，在大雅區工作"></textarea></label><button type="button" class="posting-quiet" id="posting-parse">帶入需求卡片</button><p class="posting-help" id="posting-parse-note">本機簡易解析示意，卡片內容可自行修改。</p>
      <form id="posting-form"><div class="posting-chips"><label for="posting-role">招募職稱<input id="posting-role" name="role" maxlength="80" required></label><label for="posting-hires">招募人數<input id="posting-hires" name="hires" type="number" min="1" max="100000" step="1" required></label></div>
      <button type="submit" id="posting-start">開始整理與填寫 <span aria-hidden="true">↗</span></button><details class="posting-context-details"><summary>企業與工作地點</summary><label for="posting-company">公司名稱<input id="posting-company" name="company" required maxlength="80"></label><label for="posting-address">工作地點<input id="posting-address" name="address" required maxlength="160"></label></details>
      <details class="posting-context-details"><summary>補充已知條件（選填）</summary><label for="posting-known">工作內容與條件<textarea id="posting-known" name="skills" rows="3" maxlength="1500" placeholder="已確定的技能、班別或工作內容"></textarea></label></details>
      </form>
    </div>
    <div id="posting-task" hidden><span class="posting-small-label">目前招募任務</span><h3 id="posting-task-role"></h3><p id="posting-task-summary"></p><blockquote id="posting-task-brief"></blockquote></div>
    <p id="posting-error" role="alert"></p>
    <div id="posting-source-area"><h4>內容從哪裡來？</h4><div class="posting-source-track">
      <button type="button" class="posting-source" data-source="company"><i></i><span><strong>企業資料</strong><small>目前企業情境</small></span></button>
      <button type="button" class="posting-source" data-source="template"><i></i><span><strong>職缺範本</strong><small>本機展示草稿</small></span></button>
      <button type="button" class="posting-source" data-source="web"><i></i><span><strong>網路參考</strong><small>尚未串接・未搜尋</small></span></button></div><p id="posting-source-detail" class="posting-help">點來源節點查看說明。</p></div>
    <div class="posting-review-hint" id="posting-review-hint" hidden><strong>現在輪到你確認</strong><p>直接點右側欄位編輯。薪資須填寫企業實際條件。</p><button type="button" id="posting-missing">跳到待補薪資</button></div>
    <details class="posting-log-box" id="posting-log-details"><summary>操作紀錄</summary><ol id="posting-log"></ol><p class="posting-help">固定前端事件示意，非真實模型、搜尋或 Computer Use。</p></details>
  </section>
  <section class="posting-live" aria-labelledby="posting-live-title"><div class="posting-section-title"><span id="posting-phase-dot"></span><h3 id="posting-live-title">Agent 操作實況</h3><span class="posting-live-pill" id="posting-live-pill">等待任務</span></div>
    <div class="posting-handoff" id="posting-handoff" hidden><div><span aria-hidden="true">✎</span><div><strong>現在輪到你</strong><p id="posting-focus-summary">請核對範本補寫與待補欄位。</p></div></div><div class="posting-review-filters" aria-label="審核顯示方式"><button type="button" data-review-view="all" aria-pressed="true">完整職缺</button><button type="button" data-review-view="focus" aria-pressed="false">只看待確認</button></div></div>
    <div class="posting-browser"><div class="posting-url"><i></i><i></i><i></i><span id="posting-url">demo.local / recruitment</span><b>自建模擬平台</b></div>
      <div class="posting-browser-screen" id="posting-screen"><div class="posting-platform-head"><strong>人才招募網 <small>自建展示站</small></strong><span>企業後台 / 職缺草稿</span></div>
        <div class="posting-page-top"><div><p id="posting-page-subtitle">從一個需求開始</p><h4 id="posting-page-title">準備建立下一個職缺</h4></div><span class="posting-demo">模擬 104 刊登流程</span></div>
        <div class="posting-welcome" id="posting-welcome"><div class="posting-document-icon" aria-hidden="true">＋</div><h4>你的招募需求，即將成為完整職缺</h4><p>提出需求 → 補成草稿 → 審核一次</p><div class="posting-welcome-skeleton"><i></i><i></i><i></i></div></div>
        <form id="posting-review-form" hidden><div class="posting-fields" id="posting-fields"></div></form>
        <div class="posting-success" id="posting-success" hidden><span aria-hidden="true">✓</span><h4>職缺已模擬刊登</h4><p id="posting-success-title"></p><p>只保留在目前展示頁，未傳送至 104 或其他外部網站。</p></div>
        <i class="posting-cursor" id="posting-cursor" aria-hidden="true" hidden></i>
      </div></div>
    <div class="posting-progress"><div><span id="posting-state" role="status" aria-live="polite">等待提出招募需求</span><span id="posting-count">0 / 6</span></div><progress id="posting-progress" max="6" value="0" aria-label="職缺填寫進度"></progress><div class="posting-run-actions" id="posting-run-actions" hidden><button type="button" id="posting-pause">暫停操作</button><button type="button" id="posting-skip">直接看草稿</button></div></div>
    <div class="posting-confirm" id="posting-confirm" hidden><div><strong>人工審核・只確認一次</strong><p id="posting-check-note">請確認職缺內容與待補資訊。</p></div><div><button type="button" class="posting-quiet" id="posting-edit">退回修改</button><button type="button" id="posting-publish">審核通過並模擬刊登</button></div></div>
    <div class="posting-finished" id="posting-finished" hidden><span>任務完成，已建立 1 個模擬職缺。</span><button type="button" id="posting-again">建立另一份</button></div>
  </section></div>`;
  $('city-stage').append(panel);
  const labels={company:'公司名稱',role:'職缺名稱',address:'工作地點',salary:'月薪範圍',hires:'招募人數',skills:'工作內容與技能'};
  const sourceNames={company:'企業情境',user:'使用者提供',template:'範本草稿',pending:'待確認',human:'人工修改'};
  const inputs={};
  function makeInput(name,type='text'){
    const el=document.createElement(name==='skills'?'textarea':'input');el.id=`posting-review-${name}`;el.name=name;el.setAttribute('aria-label',name==='salaryMin'?'月薪下限':name==='salaryMax'?'月薪上限':labels[name]);
    if(el.tagName==='INPUT')el.type=type;if(type==='number'){el.min='1';el.step='1';}if(name==='hires')el.max='100000';if(name==='skills'){el.rows=3;el.maxLength=1500;}else el.maxLength=160;el.required=true;inputs[name]=el;return el;
  }
  Object.entries(labels).forEach(([key,label])=>{
    const row=document.createElement('div');row.className='posting-field';row.dataset.field=key;
    const head=document.createElement('div');head.className='posting-field-head';const title=document.createElement('span');title.textContent=label;const badge=document.createElement('button');badge.type='button';badge.className='posting-provenance';badge.textContent='等待填寫';badge.addEventListener('click',()=>showProvenance(key));head.append(title,badge);
    const display=document.createElement('p');display.className='posting-field-display';display.textContent='等待填寫';
    const edit=document.createElement('div');edit.className='posting-field-edit';edit.hidden=true;
    if(key==='salary'){const wrapper=document.createElement('div');wrapper.className='posting-salary';wrapper.append(makeInput('salaryMin','number'),makeInput('salaryMax','number'));inputs.salaryMin.placeholder='月薪下限';inputs.salaryMax.placeholder='月薪上限';edit.append(wrapper);}else edit.append(makeInput(key,key==='hires'?'number':'text'));
    const tick=document.createElement('span');tick.className='posting-field-complete';tick.textContent='✓ 已填寫';tick.hidden=true;row.append(head,display,edit,tick);$('posting-fields').append(row);
  });
  let active=false,collapsedByUs=false,timer=0,typingTimer=0,epoch=0,briefText='',reviewCarry=null,reviewView='all';
  function setSidebar(collapsed){if(workspace.classList.contains('sidebar-collapsed')!==collapsed)$('sidebar-toggle').click();}
  function log(message){const li=document.createElement('li');li.textContent=message;$('posting-log').append(li);}
  function stop(){clearTimeout(timer);clearTimeout(typingTimer);epoch++;$('posting-cursor').hidden=true;$('posting-cursor').classList.remove('is-clicking');panel.querySelectorAll('.is-targeting,.is-clicked').forEach(row=>row.classList.remove('is-targeting','is-clicked'));}
  function act(name){panel.dataset.act=name;$('posting-left-heading').textContent=name==='brief'?'你的需求':'任務摘要';$('posting-live-title').textContent=name==='review'?'請你審核':name==='published'?'刊登結果':'Agent 操作實況';panel.querySelectorAll('[data-step]').forEach(el=>{const current=el.dataset.step===(name==='published'?'review':name);el.classList.toggle('is-current',current);if(current)el.setAttribute('aria-current','step');else el.removeAttribute('aria-current');});}
  function source(key){panel.querySelectorAll('.posting-source').forEach(el=>{const chosen=el.dataset.source===key;el.classList.toggle('is-active',chosen);el.setAttribute('aria-pressed',String(chosen));});}
  const notes={company:'來自目前企業情境，包含示範或自行填寫內容；不是官方企業查核。',template:'此版使用本機通用職缺範本。工作內容需人工核對，沒有使用大模型。',web:'尚未連接搜尋服務。本次沒有搜尋網路，也沒有引用網路資料。'};
  panel.querySelectorAll('.posting-source').forEach(el=>el.addEventListener('click',()=>{$('posting-source-detail').textContent=notes[el.dataset.source];}));
  function showProvenance(key){const s=panel.querySelector(`[data-field="${key}"]`).dataset.source||flow.sources[key];$('posting-source-detail').textContent=s==='pending'?'企業條件尚未提供，請由審核者補齊，不能以行情代填。':s==='template'?notes.template:s==='company'?notes.company:s==='human'?'這個欄位已由審核者修改。':'來自本次需求卡片或補充條件。';}
  function reset(){
    stop();flow.cancel();panel.dataset.paused='false';reviewView='all';panel.querySelectorAll('[data-review-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.reviewView==='all')));$('posting-pause').textContent='暫停操作';act('brief');$('posting-intake').hidden=false;$('posting-task').hidden=true;$('posting-review-hint').hidden=true;
    for(const id of ['posting-confirm','posting-finished','posting-success','posting-review-form','posting-run-actions','posting-handoff'])$(id).hidden=true;
    $('posting-welcome').hidden=false;$('posting-state').textContent='等待提出招募需求';$('posting-progress').value=0;$('posting-count').textContent='0 / 6';$('posting-source-detail').textContent='點來源節點查看說明。';$('posting-log').replaceChildren();$('posting-error').textContent='';$('posting-url').textContent='demo.local / recruitment';$('posting-page-title').textContent='準備建立下一個職缺';$('posting-live-pill').textContent='等待任務';$('posting-screen').scrollTop=0;source(null);
    panel.querySelectorAll('.posting-field').forEach(row=>{row.classList.remove('is-writing','is-filled','needs-review','review-attention','review-confirmed');row.hidden=false;row.querySelector('.posting-field-complete').hidden=true;row.querySelector('.posting-field-edit').hidden=true;row.querySelector('.posting-field-display').hidden=false;row.querySelector('.posting-field-display').textContent='等待填寫';row.querySelector('.posting-provenance').textContent='等待填寫';});
  }
  function displayValue(key){const d=flow.draft;if(key==='salary')return d.salaryMin===null?'待確認：請補充企業實際月薪範圍':`NT$ ${d.salaryMin.toLocaleString('zh-TW')} – ${d.salaryMax.toLocaleString('zh-TW')} / 月`;return key==='hires'?`${d.hires} 人`:d[key];}
  function fillRow(key,animate=false,done=()=>{}){
    const row=panel.querySelector(`[data-field="${key}"]`),display=row.querySelector('.posting-field-display'),text=displayValue(key);row.classList.add('is-filled');row.dataset.source=flow.sources[key];row.querySelector('.posting-provenance').textContent=sourceNames[flow.sources[key]];
    row.classList.toggle('needs-review',flow.sources[key]==='pending');
    if(!animate||reduced){display.textContent=text;done();return;}
    const chars=Array.from(text);let index=0;const run=epoch;display.textContent='';
    function type(){if(!active||run!==epoch||flow.state==='paused')return;index=Math.min(chars.length,index+3);display.textContent=chars.slice(0,index).join('');if(index<chars.length)typingTimer=setTimeout(type,22);else done();}type();
  }
  function readyReview(){
    clearTimeout(timer);clearTimeout(typingTimer);flow.complete();act('review');source(null);$('posting-cursor').hidden=true;$('posting-run-actions').hidden=true;$('posting-live-pill').textContent='等待人工審核';$('posting-state').textContent='草稿完成・現在輪到你確認';$('posting-url').textContent='demo.local / recruitment / review';$('posting-page-title').textContent=flow.draft.role;$('posting-review-hint').hidden=false;
    for(const key of Object.keys(labels)){fillRow(key);const row=panel.querySelector(`[data-field="${key}"]`);row.classList.remove('is-writing','is-targeting','is-clicked');row.querySelector('.posting-field-complete').hidden=true;row.querySelector('.posting-field-display').hidden=true;row.querySelector('.posting-field-edit').hidden=false;}
    for(const [key,input] of Object.entries(inputs))input.value=flow.draft[key]??'';
    if(reviewCarry){inputs.salaryMin.value=reviewCarry.salaryMin;inputs.salaryMax.value=reviewCarry.salaryMax;for(const input of [inputs.salaryMin,inputs.salaryMax])if(input.value){input.closest('.posting-field').dataset.source='human';input.closest('.posting-field').querySelector('.posting-provenance').textContent='人工修改';}}
    $('posting-confirm').hidden=false;$('posting-handoff').hidden=false;$('posting-progress').value=6;$('posting-count').textContent='6 / 6';$('posting-screen').scrollTop=0;
    updateMissing();updateReviewFocus();void $('posting-fields').offsetHeight;$('posting-screen').scrollTop=0;log('草稿已完成，停在唯一的人工審核關卡。');
  }
  function updateMissing(){const missing=!inputs.salaryMin.value||!inputs.salaryMax.value;inputs.salaryMin.closest('.posting-field').classList.toggle('needs-review',missing);$('posting-check-note').textContent=missing?'尚有月薪範圍待補充，填妥後即可一次審核刊登。':'請確認右側內容；按一次按鈕即完成審核並模擬刊登。';$('posting-missing').hidden=!missing;}
  function updateReviewFocus(applyFilter=true){
    if(panel.dataset.act!=='review')return;
    const min=Number(inputs.salaryMin.value),max=Number(inputs.salaryMax.value);
    inputs.salaryMax.setCustomValidity(inputs.salaryMin.value&&inputs.salaryMax.value&&max<min?'月薪上限不可低於下限。':'');
    let count=0;
    panel.querySelectorAll('.posting-field').forEach(row=>{
      const valid=[...row.querySelectorAll('input,textarea')].every(input=>input.checkValidity());
      const attention=RecruitmentFlow.needsReview(row.dataset.source,valid);if(attention)count++;
      row.classList.toggle('review-attention',attention);row.classList.toggle('review-confirmed',!attention);
      if(applyFilter)row.hidden=reviewView==='focus'&&!attention;
    });
    $('posting-focus-summary').textContent=count?`${count} 項待確認，包含範本補寫或尚未填妥的欄位。`:'待補項目已處理，可查看完整職缺後一次審核刊登。';
    let empty=$('posting-focus-empty');if(!empty){empty=document.createElement('p');empty.id='posting-focus-empty';empty.textContent='待確認項目已處理完成，可切回完整職缺查看。';$('posting-review-form').append(empty);}empty.hidden=reviewView!=='focus'||count>0;
  }
  panel.querySelectorAll('[data-review-view]').forEach(button=>button.addEventListener('click',()=>{reviewView=button.dataset.reviewView;panel.querySelectorAll('[data-review-view]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));updateReviewFocus();void $('posting-fields').offsetHeight;$('posting-screen').scrollTop=0;}));
  Object.entries(inputs).forEach(([key,input])=>{
    input.addEventListener('input',()=>{const row=input.closest('.posting-field');row.dataset.source='human';row.querySelector('.posting-provenance').textContent='人工修改';row.classList.remove('needs-review');updateMissing();updateReviewFocus(false);});
    input.addEventListener('focusout',()=>{if(!input.closest('.posting-field').contains(document.activeElement))updateReviewFocus();});
  });
  function finishField(key,run){
    if(!active||run!==epoch)return;
    const row=panel.querySelector(`[data-field="${key}"]`);row.classList.remove('is-writing','is-targeting','is-clicked');row.querySelector('.posting-field-complete').hidden=false;$('posting-cursor').classList.remove('is-clicking');
    log(`已填寫${labels[key]}・${sourceNames[flow.sources[key]]}`);
    timer=setTimeout(()=>{if(!active||run!==epoch)return;flow.state==='preview'?readyReview():next(run);},reduced?100:550);
  }
  function next(run){
    if(!active||run!==epoch||flow.state!=='filling')return;
    const key=flow.advance();if(!key)return;
    panel.querySelectorAll('.is-writing,.is-targeting,.is-clicked').forEach(el=>el.classList.remove('is-writing','is-targeting','is-clicked'));
    const row=panel.querySelector(`[data-field="${key}"]`);row.classList.add('is-targeting');source(flow.sources[key]==='template'?'template':'company');
    $('posting-state').textContent=`移動至${labels[key]}`;$('posting-progress').value=flow.index;$('posting-count').textContent=`${flow.index} / 6`;
    row.scrollIntoView({block:'nearest',behavior:'instant'});
    if(!reduced){const r=row.getBoundingClientRect(),s=$('posting-screen').getBoundingClientRect();$('posting-cursor').hidden=false;$('posting-cursor').style.left=`${r.left-s.left+Math.min(r.width*.55,190)}px`;$('posting-cursor').style.top=`${r.top-s.top+47+$('posting-screen').scrollTop}px`;}
    timer=setTimeout(()=>{
      if(!active||run!==epoch)return;
      row.classList.add('is-clicked');$('posting-cursor').classList.add('is-clicking');$('posting-state').textContent=`點擊${labels[key]}`;
      timer=setTimeout(()=>{
        if(!active||run!==epoch)return;
        row.classList.remove('is-targeting');row.classList.add('is-writing');$('posting-cursor').classList.remove('is-clicking');$('posting-state').textContent=`正在輸入：${labels[key]}`;
        fillRow(key,true,()=>finishField(key,run));
      },reduced?0:180);
    },reduced?0:420);
  }
  $('posting-parse').addEventListener('click',()=>{
    const text=$('posting-brief').value.trim();if(!text)return;
    const count=text.match(/(\d[\d,]*)\s*[位人名]/);if(count)$('posting-hires').value=count[1].replace(/,/g,'');
    const title=text.match(/(?:招募?|找|需要)\s*(?:\d[\d,]*\s*[位人名]\s*)?([^，。；\n]+)/);let role=title?.[1]?.replace(/\s*(?:在|於|希望|工作地點).*/,'').trim();if(role)$('posting-role').value=role;
    const district=text.match(/(西屯|南屯|北屯|大雅|大里|太平|豐原|神岡|潭子|沙鹿|梧棲|清水|烏日|霧峰|大肚|龍井|后里|大甲|東勢|新社|石岡|外埔|大安|和平|中|東|西|南|北)區/);if(district)$('posting-address').value=`臺中市${district[0]}`;
    $('posting-parse-note').textContent='已帶入能辨識的欄位，請直接修正卡片；這是前端解析示意。';const chips=panel.querySelector('.posting-chips');chips.classList.remove('is-arriving');void chips.offsetWidth;chips.classList.add('is-arriving');
  });
  $('posting-form').addEventListener('submit',event=>{
    event.preventDefault();const draft=Object.fromEntries(new FormData(event.currentTarget));
    try{flow.start(draft);}catch(error){$('posting-error').textContent=error.message;return;}
    stop();act('working');$('posting-error').textContent='';$('posting-intake').hidden=true;$('posting-task').hidden=false;$('posting-welcome').hidden=true;$('posting-review-form').hidden=false;$('posting-run-actions').hidden=false;$('posting-live-pill').textContent='模擬操作中';$('posting-state').textContent='正在整理需求與範本…';$('posting-url').textContent='demo.local / recruitment / new';$('posting-page-title').textContent='正在建立職缺草稿';$('posting-task-role').textContent=flow.draft.role;$('posting-task-summary').textContent=`${flow.draft.hires} 人・${flow.draft.address}`;briefText=$('posting-brief').value.trim();$('posting-task-brief').textContent=briefText||'依需求卡片建立任務';$('posting-log').replaceChildren();log('接收需求，開始前端模擬。');log('網路搜尋尚未串接，本次僅使用企業情境與本機範本。');source('template');const run=epoch;timer=setTimeout(()=>next(run),reduced?100:700);
  });
  $('posting-pause').addEventListener('click',()=>{
    if(flow.state==='paused'){flow.resume();panel.dataset.paused='false';$('posting-pause').textContent='暫停操作';$('posting-live-pill').textContent='模擬操作中';if(flow.index){const key=Object.keys(labels)[flow.index-1];fillRow(key);}timer=setTimeout(()=>{if(flow.index===6){flow.complete();readyReview();}else next(epoch);},250);}
    else if(['filling','preview'].includes(flow.state)){stop();flow.pause();panel.dataset.paused='true';$('posting-pause').textContent='繼續操作';$('posting-live-pill').textContent='已暫停';$('posting-state').textContent='操作已暫停，可繼續或直接看草稿';}
  });
  $('posting-skip').addEventListener('click',()=>{stop();flow.complete();readyReview();});
  $('posting-missing').addEventListener('click',()=>{reviewView='all';panel.querySelectorAll('[data-review-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.reviewView==='all')));updateReviewFocus();inputs.salaryMin.focus();});
  function back(){
    if(flow.state==='preview'){for(const key of ['company','role','address','hires'])$(`posting-${key}`).value=inputs[key].value;$('posting-known').value=inputs.skills.value;reviewCarry={salaryMin:inputs.salaryMin.value,salaryMax:inputs.salaryMax.value};}
    else reviewCarry=null;
    reset();$('posting-role').focus({preventScroll:true});
  }
  $('posting-edit').addEventListener('click',back);$('posting-again').addEventListener('click',back);
  $('posting-review-form').addEventListener('submit',event=>event.preventDefault());
  $('posting-publish').addEventListener('click',()=>{
    const form=$('posting-review-form');reviewView='all';panel.querySelectorAll('[data-review-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.reviewView==='all')));updateReviewFocus();if(!form.reportValidity())return;
    try{flow.revise(Object.fromEntries(new FormData(form)));flow.publish(true);}catch(error){$('posting-error').textContent=error.message;$('posting-state').textContent=error.message;return;}
    stop();act('published');$('posting-confirm').hidden=true;$('posting-handoff').hidden=true;$('posting-review-hint').hidden=true;$('posting-review-form').hidden=true;$('posting-success').hidden=false;$('posting-finished').hidden=false;$('posting-state').textContent='單次審核完成・已模擬刊登';$('posting-url').textContent='demo.local / recruitment / published';$('posting-live-pill').textContent='任務完成';$('posting-success-title').textContent=`${flow.draft.company}｜${flow.draft.role}・${flow.draft.hires} 人`;$('posting-screen').scrollTop=0;log('使用者一次審核通過，完成本機模擬刊登。');$('posting-again').focus({preventScroll:true});
  });
  function activate(){active=true;collapsedByUs=!workspace.classList.contains('sidebar-collapsed');setSidebar(true);window.streetMap.closeCompany(false);workspace.classList.add('posting-active');panel.hidden=false;window.radarFeatures.select('刊登召募');reviewCarry=null;reset();$('posting-company').value=$('company-name').textContent.trim()||'示範企業';$('posting-role').value=($('company-roles').textContent||'CNC 技術員').split(/[、,，]/)[0].trim();$('posting-hires').value=RecruitmentFlow.scenarioHires($('company-hires')?.textContent);$('posting-address').value=$('pin-address').textContent.trim();$('posting-brief').focus({preventScroll:true});}
  function deactivate(){if(!active)return;active=false;reset();panel.hidden=true;workspace.classList.remove('posting-active');if(collapsedByUs)setSidebar(false);window.radarFeatures.select(null);}
  $('posting-exit').addEventListener('click',()=>{deactivate();document.querySelector('[data-feature="刊登召募"]').focus({preventScroll:true});});
  window.recruitment={toggle(){active?deactivate():activate();},deactivate};
})();
