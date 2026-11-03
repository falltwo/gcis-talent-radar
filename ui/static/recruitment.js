/* Local mock recruitment platform: fixed script, no third-party calls. */
(()=>{
  'use strict';
  const $=id=>document.getElementById(id),workspace=document.querySelector('.radar-workspace');
  const flow=new RecruitmentFlow.PostingFlow();
  const panel=document.createElement('section');panel.className='posting-workspace';panel.hidden=true;panel.setAttribute('aria-label','刊登召募展示工作台');
  panel.innerHTML=`<header class="posting-header"><div><h2>刊登召募</h2><p>從招募需求到職缺發布，觀看 Agent 的模擬操作。</p></div><div><span class="posting-demo">模擬展示・不會發布到真實網站</span><button type="button" id="posting-exit">退出</button></div></header>
  <div class="posting-columns"><section class="posting-requirements" aria-labelledby="posting-need-title"><div class="posting-section-title"><span>01</span><h3 id="posting-need-title">確認招募需求</h3></div><p class="posting-help">先確認內容，再交給 Agent 填入模擬平台。</p>
  <form id="posting-form">
    <label for="posting-company">公司名稱<input id="posting-company" name="company" required maxlength="80"></label>
    <label for="posting-role">招募職稱<input id="posting-role" name="role" required maxlength="80"></label>
    <label for="posting-address">工作地點<input id="posting-address" name="address" required maxlength="160"></label>
    <fieldset><legend>月薪範圍（新臺幣）</legend><div class="posting-salary"><label for="posting-salary-min">下限<input id="posting-salary-min" name="salaryMin" type="number" min="1" step="1" required value="35000"></label><label for="posting-salary-max">上限<input id="posting-salary-max" name="salaryMax" type="number" min="1" step="1" required value="45000"></label></div></fieldset>
    <label for="posting-hires">招募人數<input id="posting-hires" name="hires" type="number" min="1" max="100000" step="1" required value="2"></label>
    <label for="posting-skills">工作內容與技能條件<textarea id="posting-skills" name="skills" rows="3" maxlength="1500" required>負責機械加工、設備操作與品質確認；具相關工作經驗佳。</textarea></label>
    <button type="submit" id="posting-start">讓 Agent 填寫職缺</button><p id="posting-error" role="alert"></p>
  </form><div class="posting-log-box"><h4>操作紀錄</h4><ol id="posting-log"></ol><p class="posting-help">固定展示腳本，非模型推理或真實網站操作。</p></div></section>
  <section class="posting-live" aria-labelledby="posting-live-title"><div class="posting-section-title"><span>02</span><h3 id="posting-live-title">Agent 即時實況虛擬瀏覽器</h3></div>
    <div class="posting-browser"><div class="posting-url"><i></i><i></i><i></i><span id="posting-url">demo.local / recruitment / new</span><b>模擬平台</b></div>
    <div class="posting-browser-screen" id="posting-screen"><div class="posting-platform-head"><strong>人才招募網 <small>自建展示站</small></strong><span>企業後台 / 新增職缺</span></div>
      <div class="posting-page-top"><div><p>建立你的下一個職缺</p><h4 id="posting-page-title">新增職缺</h4></div><span class="posting-demo">模擬 104 刊登流程</span></div>
      <div class="posting-fields" id="posting-fields"></div>
      <div class="posting-idle" id="posting-idle">確認左側需求後，Agent 會逐項填寫這裡的職缺欄位。</div>
      <div class="posting-success" id="posting-success" hidden><span aria-hidden="true">✓</span><h4>職缺已模擬發布</h4><p>這份職缺只存在此展示頁，未傳送到 104 或其他招募網站。</p></div>
      <i class="posting-cursor" id="posting-cursor" aria-hidden="true" hidden></i>
    </div></div>
    <div class="posting-progress"><div><span id="posting-state" role="status" aria-live="polite">等待確認需求</span><span id="posting-count">0 / 6</span></div><progress id="posting-progress" max="6" value="0" aria-label="職缺填寫進度"></progress></div>
    <div class="posting-confirm" id="posting-confirm" hidden><div><strong>填寫完成，等待你確認</strong><p>請檢查右側預覽內容；確認後才會模擬發布。</p></div><div><button type="button" class="posting-quiet" id="posting-edit">返回修改</button><button type="button" id="posting-publish">確認並模擬發布</button></div></div>
    <div class="posting-finished" id="posting-finished" hidden><span>展示完成。可返回需求建立下一份職缺。</span><button type="button" id="posting-again">建立另一份</button></div>
  </section></div>`;
  $('city-stage').append(panel);
  const labels={company:'公司名稱',role:'職缺名稱',address:'工作地點',salary:'月薪範圍',hires:'招募人數',skills:'工作內容與技能'};
  Object.entries(labels).forEach(([key,label])=>{const row=document.createElement('div');row.className='posting-field';row.dataset.field=key;const dt=document.createElement('span');dt.textContent=label;const dd=document.createElement('p');dd.textContent='尚未填寫';row.append(dt,dd);$('posting-fields').append(row);});
  let active=false,collapsedByUs=false,timer=0,epoch=0;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  function setSidebar(collapsed){if(workspace.classList.contains('sidebar-collapsed')!==collapsed)$('sidebar-toggle').click();}
  function log(message){const li=document.createElement('li');li.textContent=message;$('posting-log').append(li);}
  function stop(){clearTimeout(timer);epoch++;$('posting-cursor').hidden=true;}
  function lock(locked){$('posting-form').querySelectorAll('input,textarea,button').forEach(el=>el.disabled=locked);}
  function clearPreview(){
    stop();flow.cancel();lock(false);$('posting-confirm').hidden=true;$('posting-finished').hidden=true;$('posting-success').hidden=true;$('posting-idle').hidden=false;
    $('posting-state').textContent='等待確認需求';$('posting-progress').value=0;$('posting-count').textContent='0 / 6';$('posting-log').replaceChildren();$('posting-screen').scrollTop=0;$('posting-error').textContent='';$('posting-page-title').textContent='新增職缺';$('posting-url').textContent='demo.local / recruitment / new';
    panel.querySelectorAll('.posting-field').forEach(row=>{row.classList.remove('is-filled','is-writing');row.querySelector('p').textContent='尚未填寫';});
  }
  function value(key){const d=flow.draft;if(key==='salary')return `NT$ ${d.salaryMin.toLocaleString('zh-TW')} – ${d.salaryMax.toLocaleString('zh-TW')} / 月`;if(key==='hires')return `${d.hires} 人`;return d[key];}
  function fillNext(run){
    if(!active||run!==epoch||flow.state!=='filling')return;
    const key=flow.advance(),row=panel.querySelector(`[data-field="${key}"]`);if(!row)return;
    panel.querySelectorAll('.is-writing').forEach(el=>el.classList.remove('is-writing'));row.classList.add('is-writing','is-filled');row.querySelector('p').textContent=value(key);
    if(!reduced){row.scrollIntoView({block:'nearest',behavior:'smooth'});const r=row.getBoundingClientRect(),s=$('posting-screen').getBoundingClientRect();$('posting-cursor').hidden=false;$('posting-cursor').style.left=`${r.left-s.left+Math.min(r.width*.65,200)}px`;$('posting-cursor').style.top=`${r.top-s.top+30+$('posting-screen').scrollTop}px`;}
    $('posting-progress').value=flow.index;$('posting-count').textContent=`${flow.index} / 6`;$('posting-state').textContent=`正在填寫：${labels[key]}`;log(`已填寫${labels[key]}`);
    if(flow.state==='preview'){
      panel.querySelectorAll('.is-writing').forEach(el=>el.classList.remove('is-writing'));$('posting-cursor').hidden=true;$('posting-state').textContent='預覽完成・等待人工確認';$('posting-page-title').textContent=flow.draft.role;$('posting-url').textContent='demo.local / recruitment / preview';$('posting-confirm').hidden=false;log('已產生預覽，尚未發布。');$('posting-publish').focus({preventScroll:true});
    }else timer=setTimeout(()=>fillNext(run),reduced?180:750);
  }
  $('posting-form').addEventListener('submit',event=>{
    event.preventDefault();const input=Object.fromEntries(new FormData(event.currentTarget));
    try{flow.start(input);}catch(error){$('posting-error').textContent=error.message;return;}
    stop();$('posting-error').textContent='';$('posting-log').replaceChildren();lock(true);$('posting-idle').hidden=true;log('已接收確認後的企業需求，開始本機模擬填寫。');const run=epoch;timer=setTimeout(()=>fillNext(run),reduced?100:450);
  });
  function edit(){clearPreview();$('posting-role').focus({preventScroll:true});}
  $('posting-edit').addEventListener('click',edit);$('posting-again').addEventListener('click',edit);
  $('posting-publish').addEventListener('click',()=>{
    try{flow.publish(true);}catch(error){$('posting-state').textContent=error.message;return;}
    $('posting-confirm').hidden=true;$('posting-success').hidden=false;$('posting-finished').hidden=false;$('posting-state').textContent='已模擬發布・未傳送至外部網站';$('posting-url').textContent='demo.local / recruitment / published';log('使用者確認，完成本機模擬發布。');$('posting-success').scrollIntoView({block:'nearest',behavior:reduced?'instant':'smooth'});$('posting-again').focus({preventScroll:true});
  });
  function activate(){
    active=true;collapsedByUs=!workspace.classList.contains('sidebar-collapsed');setSidebar(true);window.streetMap.closeCompany(false);workspace.classList.add('posting-active');panel.hidden=false;window.radarFeatures.select('刊登召募');clearPreview();
    $('posting-company').value=$('company-name').textContent.trim()||'示範企業';$('posting-role').value=($('company-roles').textContent||'CNC 技術員').split(/[、,，]/)[0].trim();$('posting-address').value=$('pin-address').textContent.trim();$('posting-hires').value=String(RecruitmentFlow.scenarioHires($('company-hires')?.textContent));$('posting-company').focus({preventScroll:true});
  }
  function deactivate(){if(!active)return;active=false;clearPreview();panel.hidden=true;workspace.classList.remove('posting-active');if(collapsedByUs)setSidebar(false);window.radarFeatures.select(null);}
  $('posting-exit').addEventListener('click',()=>{deactivate();document.querySelector('[data-feature="刊登召募"]').focus({preventScroll:true});});
  window.recruitment={toggle(){active?deactivate():activate();},deactivate};
})();
