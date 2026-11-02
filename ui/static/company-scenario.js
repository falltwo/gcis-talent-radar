/* A user-owned planning scenario, kept separate from official observations. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const defaults={name:'宏辰精密製造',industry:'金屬製品製造業',employees:80,hires:20,roles:'CNC 技術員、品管人員',months:6,source:'sample'};
  const key='talent-radar.company-scenario.v1';
  const integer=(value,min,max)=>Number.isInteger(value)&&value>=min&&value<=max;
  const valid=value=>value&&typeof value==='object'&&
    ['name','industry','roles'].every(field=>typeof value[field]==='string'&&value[field].trim().length>0&&value[field].length<=(field==='roles'?120:60))&&
    integer(value.employees,0,1000000)&&integer(value.hires,1,100000)&&integer(value.months,1,120)&&['sample','user'].includes(value.source);
  let scenario={...defaults};
  try{const saved=JSON.parse(sessionStorage.getItem(key));if(valid(saved))scenario=saved;}catch{}
  const dialog=document.createElement('dialog');
  dialog.className='company-editor';
  dialog.setAttribute('aria-labelledby','company-editor-title');
  dialog.setAttribute('aria-describedby','company-editor-description');
  dialog.innerHTML=`
    <button id="company-editor-close" type="button" aria-label="關閉企業情境編輯">×</button>
    <h2 id="company-editor-title">編輯企業情境</h2>
    <p id="company-editor-description">填入企業現況與擴廠計畫，作為後續討論的情境。</p>
    <form id="company-form">
      <div class="company-editor-grid">
        <label>公司名稱<input id="scenario-name" name="company_name" autocomplete="organization" maxlength="60" required></label>
        <label>產業類別<input id="scenario-industry" name="industry" autocomplete="off" maxlength="60" required></label>
        <label>現有員工數<input id="scenario-employees" name="employees" type="number" inputmode="numeric" min="0" max="1000000" step="1" required></label>
        <label>預計增聘人數<input id="scenario-hires" name="hires" type="number" inputmode="numeric" min="1" max="100000" step="1" required></label>
        <label class="company-editor-wide">主要招募職務<input id="scenario-roles" name="roles" autocomplete="off" maxlength="120" placeholder="例如：CNC 技術員、品管人員" required></label>
        <label>目標到職期限（月）<input id="scenario-months" name="months" type="number" inputmode="numeric" min="1" max="120" step="1" required></label>
      </div>
      <p class="company-editor-location">候選新廠：<span id="company-editor-location"></span><br>行政區與道路可在左側「探索範圍」調整。</p>
      <p class="company-editor-hint">此情境保留於目前分頁；規劃條件不代表招募結果。</p>
      <div class="company-editor-actions"><button id="company-reset" type="button">還原示範</button><button id="company-cancel" type="button">取消</button><button type="submit" class="company-save">儲存情境</button></div>
    </form>`;
  document.body.append(dialog);
  const fields=['name','industry','employees','hires','roles','months'];
  const format=new Intl.NumberFormat('zh-TW');
  function render(){
    $('company-name').textContent=scenario.name;
    $('company-industry').textContent=scenario.industry;
    $('company-employees').textContent=format.format(scenario.employees)+' 人';
    $('company-hires').textContent=format.format(scenario.hires)+' 人';
    $('company-roles').textContent=scenario.roles;
    $('company-deadline').textContent=scenario.months+' 個月內';
    $('company-data-kind').textContent=scenario.source==='sample'?'示範資料':'自行填寫';
  }
  function fill(value){fields.forEach(field=>{$('scenario-'+field).value=value[field];$('scenario-'+field).setCustomValidity('');});}
  function close(){dialog.close();$('edit-company').focus({preventScroll:true});}
  $('edit-company').addEventListener('click',()=>{
    fill(scenario);$('company-editor-location').textContent=$('company-location').textContent;dialog.showModal();
  });
  $('company-editor-close').addEventListener('click',close);
  $('company-cancel').addEventListener('click',close);
  // Reset only edits the draft; Cancel still preserves the saved scenario.
  $('company-reset').addEventListener('click',()=>fill(defaults));
  fields.forEach(field=>$('scenario-'+field).addEventListener('input',()=>{$('scenario-'+field).setCustomValidity('');}));
  $('company-form').addEventListener('submit',event=>{
    event.preventDefault();
    for(const field of ['name','industry','roles'])if(!$('scenario-'+field).value.trim())$('scenario-'+field).setCustomValidity('請填寫內容。');
    if(!event.currentTarget.reportValidity())return;
    const draft={name:$('scenario-name').value.trim(),industry:$('scenario-industry').value.trim(),employees:Number($('scenario-employees').value),hires:Number($('scenario-hires').value),roles:$('scenario-roles').value.trim(),months:Number($('scenario-months').value)};
    draft.source=fields.every(field=>draft[field]===defaults[field])?'sample':'user';
    if(!valid(draft))return;
    scenario=draft;let stored=true;
    try{sessionStorage.setItem(key,JSON.stringify(scenario));}catch{stored=false;}
    render();close();
    $('company-save-status').textContent=stored?'已儲存於此分頁。':'已套用；此瀏覽器無法保留重新整理後的變更。';
  });
  $('close-company-window').addEventListener('click',()=>window.streetMap.closeCompany());
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&!dialog.open&&!$('company-card-popup').hidden){
      event.preventDefault();window.streetMap.closeCompany();
    }
  });
  render();
})();
