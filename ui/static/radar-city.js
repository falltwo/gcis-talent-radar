(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const main = document.querySelector('main.shell');
  const chat = $('ask-title').closest('section.panel');
  const originalDistrict = $('district');
  const options = originalDistrict.innerHTML;
  const workspace = document.createElement('section');
  workspace.className = 'radar-workspace';
  workspace.setAttribute('aria-label', '產業人才雷達街區工作台');
  workspace.innerHTML = `
    <nav class="primary-feature-nav" aria-label="主要功能">
      <button type="button" class="primary-feature-button" data-feature="校園人才媒合"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m2 9 10-5 10 5-10 5L2 9Z"/><path d="M6 11v6c4 3 8 3 12 0v-6M22 9v7"/></svg><span>校園人才媒合</span></button>
      <button type="button" class="primary-feature-button" data-feature="刊登召募"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="6" width="16" height="15" rx="2"/><path d="M9 6V3h6v3M8 11h8M8 15h5M16 17v4M14 19h4"/></svg><span>刊登召募</span></button>
      <button type="button" class="primary-feature-button" data-feature="獵頭Agent"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="9" r="4"/><path d="M3 21v-2a7 7 0 0 1 11-5"/><circle cx="17" cy="17" r="4"/><path d="m20 20 2 2"/></svg><span>獵頭Agent</span></button>
    </nav>
    <aside class="radar-sidebar" aria-label="資料助理與地點選擇">
      <div class="radar-brand"><span class="brand-symbol" aria-hidden="true">◎</span><div><strong>產業人才雷達</strong><small>TAICHUNG · TALENT RADAR</small></div></div>
      <div class="radar-chat" id="radar-chat"></div>
      <form class="radar-location" id="sidebar-location"><h3>探索範圍</h3><div class="location-fields"><div><label for="city-district">行政區</label><select id="city-district">${options}</select></div><div><label for="city-road">道路／街道</label><select id="city-road" required disabled><option value="">讀取道路中…</option></select></div></div><button type="submit" id="city-update" disabled>更新探索位置 ↗</button><p id="road-note">道路選單來自本地公司登記地址，並非完整道路名冊。</p></form>
    </aside>
    <div class="city-stage" id="city-stage">
      <div class="city-topbar"><div><p>EXPLORE YOUR NEXT LOCATION</p><h1 id="city-heading" tabindex="-1">從這裡，看見產業的可能。</h1><div class="city-address" id="city-address">臺中市 · 大雅區</div></div><button class="quiet-button" id="replay-intro" aria-label="重新開啟雷達與地點選擇" title="重新選擇地點">◎</button></div>
      <div id="city-map" role="region" aria-label="真實道路與立體建物地圖"></div>
      <div class="map-toolbar"><button id="map-rotate" type="button">旋轉 ↻</button><button id="map-flat" type="button">平面 2D</button><button id="map-home" type="button">回到選點</button></div>
      <div class="map-status-bar"><span id="map-status" role="status" aria-live="polite">選擇道路後載入地圖</span><button id="map-retry" type="button">重試</button></div>
      <section class="city-callout company-card" id="company-card-popup" aria-labelledby="company-card-title" hidden>
        <div class="company-card-head"><h2 id="company-card-title">我的企業情境</h2><div class="company-head-actions"><span id="company-data-kind" class="company-data-kind">示範資料</span><button type="button" id="close-company-window" aria-label="關閉企業情境浮窗">×</button></div></div>
        <h3 id="company-name"></h3><div id="company-card-content"><p id="company-industry"></p>
        <div class="company-current"><span>現有員工</span><strong id="company-employees"></strong></div>
        <div class="company-plan"><h4>本次擴廠規劃</h4><dl>
          <div><dt>候選新廠</dt><dd id="company-location">尚未選擇地點</dd></div>
          <div><dt>預計增聘</dt><dd id="company-hires"></dd></div>
          <div><dt>主要職務</dt><dd id="company-roles"></dd></div>
          <div><dt>目標到職</dt><dd id="company-deadline"></dd></div>
        </dl></div>
        <button type="button" id="edit-company">編輯企業情境</button>
        <p class="company-context-note">企業情境資料，非官方統計。</p>
        <div id="company-save-status" role="status" aria-live="polite"></div>
        <details class="company-position"><summary>位置詳情</summary><p id="pin-address" tabindex="-1">尚未選擇地點</p><p id="pin-precision">紅點標示查得的道路位置，非門牌。</p><p id="map-coordinates"></p><a id="map-source" hidden target="_blank" rel="noopener noreferrer">在 OpenStreetMap 查看 ↗</a></details></div>
      </section>
      <div class="city-bottom"><div class="city-caption"><span>真實道路與建物輪廓 · 缺少高度時為估計模型</span><a href="/compare">比較不同區域 ↗</a></div><div class="city-stats" aria-label="官方資料摘要" id="city-stats"></div></div>
    </div>`;
  main.prepend(workspace);
  $('radar-chat').append(chat);
  const featureDialog=document.createElement('dialog');
  featureDialog.className='feature-placeholder';
  featureDialog.setAttribute('aria-labelledby','feature-placeholder-title');
  featureDialog.innerHTML='<h2 id="feature-placeholder-title"></h2><p>這個功能正在準備中。</p><button type="button">知道了</button>';
  document.body.append(featureDialog);
  let featureTrigger;
  let activeFeature=null;
  function selectFeature(name){
    activeFeature=name;
    workspace.querySelector('.primary-feature-nav').classList.toggle('has-selection',!!name);
    workspace.querySelectorAll('[data-feature]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.feature===name)));
  }
  window.radarFeatures={select:selectFeature};
  selectFeature(null);
  workspace.querySelectorAll('[data-feature]').forEach(button=>button.addEventListener('click',()=>{
    if(button.dataset.feature==='校園人才媒合'&&window.campusMatching){window.campusMatching.toggle();return;}
    window.campusMatching?.deactivate();
    featureTrigger=button;selectFeature(button.dataset.feature);
    $('feature-placeholder-title').textContent=button.dataset.feature;featureDialog.showModal();
  }));
  featureDialog.querySelector('button').addEventListener('click',()=>featureDialog.close());
  featureDialog.addEventListener('close',()=>{selectFeature(null);featureTrigger?.focus({preventScroll:true});});
  $('expansion').classList.add('radar-details');
  const intro = document.createElement('section');
  intro.className = 'radar-intro';
  intro.setAttribute('aria-label', '選擇探索地點');
  intro.innerHTML = `
    <div class="intro-inner">
      <div class="radar-copy"><h1 class="radar-title">產業人才雷達</h1></div>
      <button id="radar-start" class="radar-launch" type="button" aria-label="開始探索，選擇臺中市行政區與道路"></button>
        <div class="radar-object" aria-hidden="true">
          <div class="radar-aura"></div>
          <div class="radar-disc">
            <svg viewBox="0 0 500 500" class="radar-grid"><circle cx="250" cy="250" r="238"/><circle cx="250" cy="250" r="180"/><circle cx="250" cy="250" r="120"/><circle cx="250" cy="250" r="60"/><path d="M12 250H488M250 12V488"/><g class="radar-ticks"></g></svg>
            <div class="radar-sweep"></div><div class="radar-targets"></div><i class="radar-center"></i>
          </div>
        </div>
        <div class="radar-invitation"><span>點擊任意處，開始探索</span><small>或按任意一般按鍵</small></div>
      <button id="radar-motion" class="radar-motion" type="button" aria-pressed="false">暫停動態</button>
    </div>
    <dialog class="explore-dialog" aria-labelledby="explore-dialog-title" aria-describedby="explore-dialog-description">
      <button id="explore-close" type="button" aria-label="關閉地點選擇，回到雷達">×</button>
      <h2 id="explore-dialog-title" tabindex="-1">你想從哪裡開始探索？</h2>
      <p id="explore-dialog-description">選一個地點，看看周邊的產業與招募環境。</p>
      <form class="explore-form" id="intro-location">
        <div class="location-fields"><div><label for="intro-district">臺中市行政區</label><select id="intro-district" name="district" autocomplete="off">${options}</select></div><div><label for="intro-road">道路／街道</label><select id="intro-road" name="road" autocomplete="off" required disabled><option value="">讀取道路中…</option></select></div></div>
        <button id="intro-submit" type="submit" disabled>探索這個地點</button>
        <p id="intro-note" role="status">道路選項來自公司登記地址；定位與地圖資料來自 OpenStreetMap。</p>
      </form>
    </dialog>`;
  document.body.append(intro);
  workspace.inert = true;
  $('expansion').inert = true;
  document.body.style.overflow = 'hidden';
  let roadIndex = {};
  let selected = {district: originalDistrict.value, road: ''};
  const entrance = window.createRadarEntrance(intro);

  function fillRoads(prefix, preferred = '') {
    const select = $(prefix + '-road');
    const roads = roadIndex[$(prefix + '-district').value] || [];
    select.replaceChildren();
    if (!roads.length) select.add(new Option('本區道路資料未收錄', ''));
    for (const road of roads) select.add(new Option(road, road));
    if (roads.includes(preferred)) select.value = preferred;
    select.disabled = !roads.length;
    $(prefix === 'intro' ? 'intro-submit' : 'city-update').disabled = !roads.length;
  }
  ['intro','city'].forEach(prefix => $(prefix + '-district').addEventListener('change', () => fillRoads(prefix)));
  fetch('/static/road-index.json').then(response => {if (!response.ok) throw Error('道路資料讀取失敗'); return response.json();}).then(data => {
    roadIndex = data.districts;
    fillRoads('intro', '中清路三段'); fillRoads('city', '中清路三段');
  }).catch(() => {
    $('intro-note').textContent = '道路資料讀取失敗，請重新整理頁面後再試。';
    $('road-note').textContent = '道路資料讀取失敗，請重新整理頁面後再試。';
  });
  function selectLocation(district,road) {
    selected={district,road};
    $('city-district').value=district;fillRoads('city',road);
    originalDistrict.value=district;
    $('city-address').textContent=`臺中市 / ${district} / ${road}`;
    $('pin-address').textContent=`${district}・${road}`;
    $('company-location').textContent=`${district}・${road}`;
    $('city-heading').textContent=`探索${district}的產業風景`;
    $('ask-input').placeholder=`例如：${district}製造業現在的職缺有多少？`;
    const suggestions=chat.querySelectorAll('.suggest');
    suggestions[0].textContent=`${district}製造業現在的職缺有多少？`;
    suggestions[1].textContent=`${district === '西屯區' ? '大雅區' : '西屯區'}製造業現在的職缺有多少？`;
    $('city-stage').classList.remove('city-ready');
    window.streetMap.locate(district,road);
    requestAnimationFrame(()=>requestAnimationFrame(()=>$('city-stage').classList.add('city-ready')));
    $('query-form').requestSubmit();
  }
  $('intro-location').addEventListener('submit',e=>{
    e.preventDefault();if(!$('intro-road').value)return;
    selectLocation($('intro-district').value,$('intro-road').value);
    entrance.leave(()=>{
      intro.inert=true;workspace.inert=false;$('expansion').inert=false;
      document.body.style.overflow='';$('city-heading').focus({preventScroll:true});
    });
  });
  $('sidebar-location').addEventListener('submit',e=>{e.preventDefault();if($('city-road').value)selectLocation($('city-district').value,$('city-road').value);});
  $('replay-intro').addEventListener('click',()=>{
    window.campusMatching?.deactivate();
    entrance.show();
    $('intro-district').value=selected.district;fillRoads('intro',selected.road);
    workspace.inert=true;$('expansion').inert=true;document.body.style.overflow='hidden';
  });
  // Keep the existing expansion form and the workspace location in sync.
  originalDistrict.addEventListener('change',()=>{
    $('city-district').value=originalDistrict.value;fillRoads('city');
    if($('city-road').value) selectLocation(originalDistrict.value,$('city-road').value);
  });
  const stats=[['factory-value','製造業工廠','行政區快照'],['jobs-value','公開職缺刊登','行政區 · 非缺工人數'],['company-value','新設公司','臺中全市'],['wage-value','平均投保薪資','臺中全市 · 非實領薪資']];
  function updateStats(){
    $('city-stats').replaceChildren();
    for(const [id,label,scope] of stats){
      const box=document.createElement('div');box.className='city-stat';
      const title=document.createElement('small');title.textContent=label;
      const value=document.createElement('strong');value.textContent=$('results').hidden?'—':($(id).textContent||'—');
      const caption=document.createElement('span');caption.textContent=scope;
      box.append(title,value,caption);$('city-stats').append(box);
    }
  }
  new MutationObserver(updateStats).observe($('results'),{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['hidden']});
  updateStats();
})();
