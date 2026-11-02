/* Frontend demonstration adapter. No real school or skill-match claims. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id),workspace=document.querySelector('.radar-workspace');
  const chat=$('ask-title').closest('section.panel'),chatHost=$('radar-chat');
  const tabs=document.createElement('div');tabs.className='campus-tabs';tabs.hidden=true;
  tabs.innerHTML='<button type="button" aria-pressed="true" data-view="schools">學校清單</button><button type="button" aria-pressed="false" data-view="assistant">資料助理</button>';
  const panel=document.createElement('section');panel.id='campus-panel';panel.hidden=true;
  panel.innerHTML=`<div class="campus-panel-heading"><h2>校園人才媒合</h2><span class="campus-demo-badge">展示版</span></div>
    <p class="campus-demo-note">虛構校區，非真實學校與媒合結果。</p>
    <form id="campus-filters"><label for="campus-roles">想招募的職務<input id="campus-roles" name="roles" maxlength="120" autocomplete="off" placeholder="例如：CNC 技術員、品管人員"></label>
    <label for="campus-radius">搜尋範圍<span class="campus-radius-field"><input id="campus-radius" name="radius" type="number" min="0.1" step="any" value="15" required inputmode="decimal" aria-describedby="campus-radius-unit"><span id="campus-radius-unit">公里</span></span></label><button type="submit">更新展示結果</button></form>
    <p id="campus-results-status" role="status" aria-live="polite"></p><div id="campus-results"></div>
    <details class="campus-basket"><summary id="campus-basket-summary">合作候選（0）</summary><p>此分頁的展示清單，加入不代表已聯絡或合作。</p><div id="campus-basket-list"></div></details>`;
  chatHost.prepend(tabs,panel);
  const context=document.createElement('div');context.className='campus-context';context.hidden=true;
  context.innerHTML='<div><strong>校園合作候選</strong><span>展示模式：虛構校區與示範距離</span></div><div><button type="button" id="campus-show-all">查看全部</button><button type="button" id="campus-exit">退出媒合</button></div>';
  $('city-stage').append(context);
  let active=false,view='schools',dataset=null,loading=null,results=[],nodes=[],popup=null,selectedId=null,frame=0,generation=0;
  let originKey='',basket=new Map();
  const lineSource='campus-demo-connections',headSource='campus-demo-heads';
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  function node(tag,text,cls){const el=document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;}
  function status(text){$('campus-results-status').textContent=text;}
  const norm=s=>String(s).toLowerCase().replace(/\s+/g,'');
  function matchRoles(item,roles){return !roles.trim()||item.keywords.some(keyword=>norm(roles).includes(norm(keyword)));}
  function demoCoordinates(origin,offset){const [east,north]=offset;return [origin[0]+east/(111.32*Math.cos(origin[1]*Math.PI/180)),origin[1]+north/110.57];}
  function distance(a,b){const rad=x=>x*Math.PI/180;const dLat=rad(b[1]-a[1]),dLon=rad(b[0]-a[0]);const h=Math.sin(dLat/2)**2+Math.cos(rad(a[1]))*Math.cos(rad(b[1]))*Math.sin(dLon/2)**2;return 6371*2*Math.atan2(Math.sqrt(h),Math.sqrt(Math.max(0,1-h)));}
  function curve(a,b){const dx=b[0]-a[0],dy=b[1]-a[1];const control=[(a[0]+b[0])/2-dy*.18,(a[1]+b[1])/2+dx*.18];return Array.from({length:65},(_,i)=>{const t=i/64;return [(1-t)**2*a[0]+2*(1-t)*t*control[0]+t*t*b[0],(1-t)**2*a[1]+2*(1-t)*t*control[1]+t*t*b[1]];});}
  async function loadData(){
    if(dataset)return dataset;
    if(!loading)loading=fetch('/static/campus-demo.json').then(r=>{if(!r.ok)throw Error('展示資料載入失敗，請稍後重試。');return r.json();}).then(data=>{
      if(data.mode!=='demo'||!Array.isArray(data.campuses)||data.campuses.some(item=>!item.id||!item.name||!Array.isArray(item.keywords)||!Array.isArray(item.offset_km)||item.offset_km.length!==2||!item.offset_km.every(Number.isFinite)))throw Error('展示資料格式不完整。');dataset=data;return data;
    }).finally(()=>{loading=null;});
    return loading;
  }
  function selectView(next){view=next;panel.hidden=!active||view!=='schools';chat.hidden=active&&view==='schools';tabs.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===view)));}
  tabs.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>selectView(b.dataset.view)));
  function closePopup(){popup?.remove();popup=null;}
  function clearMap(){
    cancelAnimationFrame(frame);closePopup();nodes.forEach(n=>n.remove());nodes=[];
    const map=window.streetMap.getMap();
    if(map){['campus-demo-head','campus-demo-line','campus-demo-halo'].forEach(id=>{if(map.getLayer(id))map.removeLayer(id);});[lineSource,headSource].forEach(id=>{if(map.getSource(id))map.removeSource(id);});}
  }
  function highlight(id){
    selectedId=id;const map=window.streetMap.getMap();
    if(map?.getLayer('campus-demo-line'))map.setPaintProperty('campus-demo-line','line-color',['case',['==',['get','id'],id||''],'#3c79c8','#91b0d6']);
    nodes.forEach(marker=>marker.getElement().classList.toggle('is-selected',marker.getElement().dataset.campusId===id));
    $('campus-results').querySelectorAll('[data-campus-id]').forEach(button=>{const selected=button.dataset.campusId===id;button.classList.toggle('is-selected',selected);button.setAttribute('aria-pressed',String(selected));});
  }
  function fitAll(){
    const map=window.streetMap.getMap(),location=window.streetMap.getLocation();if(!map||!location||!results.length)return;
    const bounds=new maplibregl.LngLatBounds(location.coordinates,location.coordinates);results.forEach(item=>bounds.extend(item.coordinates));
    map.fitBounds(bounds,{padding:{top:140,bottom:85,left:45,right:45},maxZoom:13,pitch:35,bearing:-15,duration:reduced?0:1000});
  }
  function updateBasket(){
    $('campus-basket-summary').textContent=`合作候選（${basket.size}）`;
    const box=$('campus-basket-list');box.replaceChildren();
    if(!basket.size)box.append(node('p','尚未加入候選校區。'));
    basket.forEach(item=>{const row=node('div',null,'campus-basket-row');row.append(node('span',item.name));const remove=node('button','移除');remove.type='button';remove.setAttribute('aria-label',`移除${item.name}`);remove.addEventListener('click',()=>{basket.delete(item.id);updateBasket();updateAddButton();});row.append(remove);box.append(row);});
  }
  function updateAddButton(){if(popup){const button=popup.getElement().querySelector('.campus-add');if(button)button.textContent=basket.has(selectedId)?'已加入候選・點擊移除':'＋ 加入合作候選';}}
  function openSchool(item){
    const map=window.streetMap.getMap();if(!active||!map)return;
    closePopup();window.streetMap.closeCompany(false);highlight(item.id);
    const box=node('section',null,'campus-school-popup');box.setAttribute('aria-label',item.name+' 展示資訊');
    const head=node('div',null,'campus-popup-head');head.append(node('span','虛構校區・展示資料','campus-demo-badge'));const close=node('button','×');close.type='button';close.setAttribute('aria-label','關閉學校資訊');close.addEventListener('click',()=>{closePopup();nodes.find(m=>m.getElement().dataset.campusId===item.id)?.getElement().focus({preventScroll:true});});head.append(close);box.append(head,node('h2',item.name),node('p',item.campus_name));
    box.append(node('h3','為什麼找到這個校系？'));item.departments.forEach(dept=>box.append(node('span',dept,'campus-dept')));box.append(node('p',item.reason));
    const facts=node('dl');[['示範直線距離',item.distance_km.toFixed(1)+' 公里'],['相關職務示例',item.related_roles.join('、')],['畢業生與學年','待接正式資料'],['官方合作窗口','待接正式資料']].forEach(([title,value])=>{facts.append(node('dt',title),node('dd',value));});box.append(facts,node('p','座標以企業選點為中心產生，並非真實校址。','campus-popup-note'));
    const add=node('button',basket.has(item.id)?'已加入候選・點擊移除':'＋ 加入合作候選','campus-add');add.type='button';add.addEventListener('click',()=>{if(basket.has(item.id))basket.delete(item.id);else basket.set(item.id,item);updateBasket();updateAddButton();status(basket.has(item.id)?`${item.name}已加入展示合作候選，尚未聯絡。`:`已移除${item.name}。`);});box.append(add);
    // Laid out off-screen first so the anchor is chosen from the card's real height.
    Object.assign(box.style,{position:'absolute',visibility:'hidden',width:'310px'});$('city-stage').append(box);
    const anchor=window.streetMap.popupAnchor(box,item.coordinates);
    Object.assign(box.style,{position:'',visibility:'',width:''});
    popup=new maplibregl.Popup({closeButton:false,closeOnClick:false,anchor,offset:23,maxWidth:'310px',focusAfterOpen:false}).setLngLat(item.coordinates).setDOMContent(box).addTo(map);
    $('city-stage').classList.add('campus-popup-open');popup.on('close',()=>{$('city-stage').classList.remove('campus-popup-open');});
    close.focus({preventScroll:true});
  }
  function renderList(){
    const box=$('campus-results');box.replaceChildren();
    results.forEach(item=>{const button=node('button',null,'campus-result');button.type='button';button.dataset.campusId=item.id;button.setAttribute('aria-pressed','false');button.append(node('strong',item.name),node('span',item.departments.join('、')),node('small',`示範距離 ${item.distance_km.toFixed(1)} 公里・虛構校區`),node('span','查看校系與推薦理由','campus-result-action'));button.addEventListener('click',()=>openSchool(item));box.append(button);});
  }
  function drawMap(location){
    const map=window.streetMap.getMap();if(!map||!results.length)return;
    const empty={type:'FeatureCollection',features:[]};
    map.addSource(lineSource,{type:'geojson',data:empty});map.addSource(headSource,{type:'geojson',data:empty});
    map.addLayer({id:'campus-demo-halo',type:'line',source:lineSource,paint:{'line-width':9,'line-color':'#8ebaff','line-opacity':.2,'line-blur':3}});
    map.addLayer({id:'campus-demo-line',type:'line',source:lineSource,paint:{'line-width':2.6,'line-color':'#7ea9df','line-opacity':.9}});
    map.addLayer({id:'campus-demo-head',type:'circle',source:headSource,paint:{'circle-radius':4,'circle-color':'#e4f4ff','circle-stroke-color':'#80b4ee','circle-stroke-width':2,'circle-blur':.15}});
    nodes=results.map(item=>{const button=node('button',null,'campus-node');button.type='button';button.dataset.campusId=item.id;button.disabled=!reduced;button.setAttribute('aria-label',item.name+'，虛構校區，查看學校資訊');button.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m2 9 10-5 10 5-10 5L2 9Z M6 11v6q6 5 12 0v-6 M22 9v7"/></svg>';button.append(node('span',item.name));button.addEventListener('click',()=>openSchool(item));return new maplibregl.Marker({element:button,anchor:'center'}).setLngLat(item.coordinates).addTo(map);});
    const paths=results.map(item=>curve(location.coordinates,item.coordinates)),started=performance.now();
    function draw(now){
      if(!active||!map.getSource(lineSource))return;
      let done=true;const heads=[];
      const features=results.map((item,i)=>{const progress=reduced?1:Math.min(1,Math.max(0,(now-started-i*180)/1300));if(progress<1)done=false;const count=Math.max(2,Math.ceil(progress*64)+1);const points=paths[i].slice(0,count);if(progress>0&&progress<1)heads.push({type:'Feature',geometry:{type:'Point',coordinates:points.at(-1)},properties:{}});if(progress===1){nodes[i].getElement().classList.add('is-visible');nodes[i].getElement().disabled=false;}return {type:'Feature',properties:{id:item.id},geometry:{type:'LineString',coordinates:points}};});
      map.getSource(lineSource).setData({type:'FeatureCollection',features});map.getSource(headSource).setData({type:'FeatureCollection',features:heads});
      if(!done)frame=requestAnimationFrame(draw);
    }
    draw(performance.now());fitAll();
  }
  async function refresh(){
    const request=++generation;clearMap();results=[];$('campus-results').replaceChildren();
    const location=window.streetMap.getLocation(),map=window.streetMap.getMap();
    if(!location||!map){status('等待所選道路定位完成；定位成功後會顯示展示校區。');return;}
    status('正在讀取展示資料…');
    try{
      const data=await loadData();if(!active||request!==generation)return;
      const nextOrigin=location.coordinates.join(',');
      if(originKey!==nextOrigin){basket.clear();originKey=nextOrigin;updateBasket();}
      const radiusInput=$('campus-radius');
      const radius=Number(radiusInput.value),roles=$('campus-roles').value;
      if(!radiusInput.checkValidity()||!Number.isFinite(radius)||radius<=0){status('請輸入至少 0.1 公里的有效搜尋範圍。');return;}
      results=data.campuses.map(item=>{const coordinates=demoCoordinates(location.coordinates,item.offset_km);return {...item,coordinates,distance_km:distance(location.coordinates,coordinates)};}).filter(item=>item.distance_km<=radius&&matchRoles(item,roles)).sort((a,b)=>a.distance_km-b.distance_km);
      renderList();updateBasket();
      if(!results.length){status('展示資料中沒有符合條件的校區。可擴大範圍，或改用 CNC、品管、設備等示範職務；不代表附近沒有真實學校。');return;}
      status(`顯示 ${results.length} 個虛構展示校區，非正式媒合結果。`);drawMap(location);
    }catch(error){if(active&&request===generation)status(error.message);}
  }
  function activate(){active=true;workspace.classList.add('campus-active');tabs.hidden=false;context.hidden=false;window.radarFeatures.select('校園人才媒合');window.streetMap.closeCompany(false);$('campus-roles').value=$('company-roles').textContent||'';selectView('schools');refresh();}
  function deactivate(){if(!active)return;active=false;++generation;clearMap();workspace.classList.remove('campus-active');tabs.hidden=true;context.hidden=true;panel.hidden=true;chat.hidden=false;window.radarFeatures.select(null);}
  window.campusMatching={toggle(){active?deactivate():activate();},deactivate};
  $('campus-filters').addEventListener('submit',event=>{event.preventDefault();refresh();});
  $('campus-exit').addEventListener('click',deactivate);$('campus-show-all').addEventListener('click',()=>{closePopup();fitAll();});
  document.addEventListener('streetmap:location',()=>{if(active)refresh();});
  document.addEventListener('streetmap:location-changing',()=>{if(active){++generation;clearMap();$('campus-results').replaceChildren();status('正在切換探索地點…');}});
  document.addEventListener('streetmap:location-error',event=>{if(active)status(event.detail+' 校園展示需要先完成道路定位。');});
  document.addEventListener('streetmap:company-open',closePopup);
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&popup&&!document.querySelector('dialog[open]'))closePopup();});
})();
