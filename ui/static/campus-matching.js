/* Frontend demonstration adapter. No real school or skill-match claims. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id),workspace=document.querySelector('.radar-workspace');
  const chat=$('ask-title').closest('section.panel'),chatHost=$('radar-chat');
  const tabs=document.createElement('div');tabs.className='campus-tabs';tabs.hidden=true;
  tabs.innerHTML='<button type="button" aria-pressed="true" data-view="schools">學校清單</button><button type="button" aria-pressed="false" data-view="assistant">資料助理</button>';
  const panel=document.createElement('section');panel.id='campus-panel';panel.hidden=true;
  panel.innerHTML=`<div class="campus-panel-heading"><h2>校園人才媒合</h2><span class="campus-source-badge" id="campus-source-label">官方校區名冊</span></div>
    <p class="campus-directory-note">用職務找科系，或直接搜尋臺中的學校與系所。</p>
    <form id="campus-filters"><label for="campus-query">職務、學校或系所<input id="campus-query" name="q" maxlength="80" autocomplete="off" placeholder="如軟體工程師、逢甲、機械工程"></label>
    <label for="campus-radius">搜尋範圍<span class="campus-radius-field"><input id="campus-radius" name="radius" type="number" min="0.1" step="any" value="15" required inputmode="decimal" aria-describedby="campus-radius-unit"><span id="campus-radius-unit">公里</span></span></label><button type="submit" id="campus-search">搜尋校區</button><label class="campus-related-toggle"><input id="campus-related" type="checkbox" checked>包含相關領域（分開標示）</label></form>
    <p id="campus-results-status" role="status" aria-live="polite"></p><button type="button" id="campus-retry" hidden>重新查詢</button><div id="campus-suggestions"></div><div id="campus-results" aria-busy="false"></div>
    <details class="campus-basket"><summary id="campus-basket-summary">合作候選（0）</summary><p>清單只保留於本次探索；加入不代表已聯絡或合作。</p><div id="campus-basket-list"></div></details>`;
  chatHost.prepend(tabs,panel);
  const context=document.createElement('div');context.className='campus-context';context.hidden=true;
  context.innerHTML='<div><strong>校園合作候選</strong><span>真實校區位置 · 直線距離，非通勤距離</span></div><div><button type="button" id="campus-show-all">查看全部</button><button type="button" id="campus-exit">退出媒合</button></div>';
  $('city-stage').append(context);
  let active=false,view='schools',results=[],nodes=[],popup=null,selectedId=null,frame=0,generation=0,controller=null;
  let originKey='',releaseId='',academicYear=null,basket=new Map();
  let camera=null,focusTrigger=null;
  const lineSource='campus-demo-connections',headSource='campus-demo-heads',radiusSource='campus-search-radius',sweepSource='campus-radius-sweep-area';
  let radiusRing=[],shownCount=0,popupBox=null,lastSweep='';
  // MapLibre cannot offset a dash, so stepping through these patterns moves it along the line.
  const DASH_FRAMES=[[0,4,3],[.5,4,2.5],[1,4,2],[1.5,4,1.5],[2,4,1],[2.5,4,.5],[3,4,0],[0,.5,3,3.5],[0,1,3,3],[0,1.5,3,2.5],[0,2,3,2],[0,2.5,3,1.5],[0,3,3,1],[0,3.5,3,.5]];
  function flowLines(map){
    let shown=-1;
    const step=now=>{
      if(!active||!map.getLayer('campus-demo-line'))return;
      const index=Math.floor(now/75)%DASH_FRAMES.length;
      if(index!==shown){shown=index;map.setPaintProperty('campus-demo-line','line-dasharray',DASH_FRAMES[index]);}
      frame=requestAnimationFrame(step);
    };
    frame=requestAnimationFrame(step);
  }
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  function node(tag,text,cls){const el=document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;}
  function status(text){$('campus-results-status').textContent=text;}
  const campusName=item=>`${item.institution_name}・${item.name}`;
  function link(label,url){
    try{const parsed=new URL(url);if(!['http:','https:'].includes(parsed.protocol))return null;const a=node('a',label);a.href=parsed.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch{return null;}
  }
  function offsetCoordinates(origin,offset){const [east,north]=offset;return [origin[0]+east/(111.32*Math.cos(origin[1]*Math.PI/180)),origin[1]+north/110.57];}
  function curve(a,b){const dx=b[0]-a[0],dy=b[1]-a[1];const control=[(a[0]+b[0])/2-dy*.18,(a[1]+b[1])/2+dx*.18];return Array.from({length:65},(_,i)=>{const t=i/64;return [(1-t)**2*a[0]+2*(1-t)*t*control[0]+t*t*b[0],(1-t)**2*a[1]+2*(1-t)*t*control[1]+t*t*b[1]];});}
  function readData(data){
    if(!data?.release_id||!Number.isInteger(data.academic_year)||!Array.isArray(data.items))throw Error('校區資料格式不完整，請重新查詢。');
    const ids=new Set();
    return data.items.map(item=>{
      if(!item.campus_id||ids.has(item.campus_id)||!item.institution_name||!item.name||!Array.isArray(item.departments)||!Number.isFinite(item.longitude)||!Number.isFinite(item.latitude)||item.longitude < -180||item.longitude > 180||item.latitude < -90||item.latitude > 90||!Number.isFinite(item.distance_km)||item.distance_km<0)throw Error('校區座標或資料不完整，請重新查詢。');
      ids.add(item.campus_id);return {...item,id:item.campus_id,coordinates:[item.longitude,item.latitude]};
    });
  }
  function cancelRequest(){++generation;controller?.abort();controller=null;}
  function busy(value){$('campus-results').setAttribute('aria-busy',String(value));$('campus-search').disabled=value;$('campus-search').textContent=value?'查詢中…':'搜尋校區';}
  function selectView(next){view=next;panel.hidden=!active||view!=='schools';chat.hidden=active&&view==='schools';tabs.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===view)));}
  tabs.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>selectView(b.dataset.view)));
  function closePopup({restore=true, focus=false}={}){
    if(!popup)return;
    popup.remove();popup=null;popupBox?.remove();popupBox=null;
    if(restore)camera?.restore();
    if(focus)focusTrigger?.focus({preventScroll:true});
    focusTrigger=null;
  }
  function clearResults(){
    clearMap();results=[];$('campus-results').replaceChildren();
    $('campus-retry').hidden=true;$('campus-suggestions').replaceChildren();
  }
  // Once dragged the card leaves the map popup, so panning the map no longer carries it along.
  function makeDraggable(box,handle){
    handle.addEventListener('pointerdown',down=>{
      if(down.button!==0||down.target.closest('button'))return;
      down.preventDefault();
      const stage=$('city-stage'),bounds=stage.getBoundingClientRect(),start=box.getBoundingClientRect();
      const grabX=down.clientX-start.left,grabY=down.clientY-start.top;
      if(!box.classList.contains('is-floating')){
        Object.assign(box.style,{left:start.left-bounds.left+'px',top:start.top-bounds.top+'px',width:start.width+'px'});
        box.classList.add('is-floating');stage.append(box);popup.getElement().style.visibility='hidden';
        handle.querySelector('button').focus({preventScroll:true});
      }
      box.classList.add('is-dragging');
      const move=event=>{
        box.style.left=Math.min(Math.max(8,event.clientX-bounds.left-grabX),bounds.width-start.width-8)+'px';
        box.style.top=Math.min(Math.max(8,event.clientY-bounds.top-grabY),bounds.height-60)+'px';
      };
      const up=()=>{box.classList.remove('is-dragging');document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',up);document.removeEventListener('pointercancel',up);};
      document.addEventListener('pointermove',move);document.addEventListener('pointerup',up);document.addEventListener('pointercancel',up);
    });
  }
  function clearMap(){
    cancelAnimationFrame(frame);closePopup({restore:false});nodes.forEach(n=>n.remove());nodes=[];
    const map=window.streetMap.getMap();
    radiusRing=[];
    if(map){['campus-demo-head','campus-demo-line','campus-demo-halo','campus-radius-fill','campus-radius-edge','campus-radius-sweep'].forEach(id=>{if(map.getLayer(id))map.removeLayer(id);});[lineSource,headSource,radiusSource,sweepSource].forEach(id=>{if(map.getSource(id))map.removeSource(id);});}
  }
  function drawRadius(origin,radius){
    const map=window.streetMap.getMap();
    radiusRing=Array.from({length:65},(_,i)=>{const angle=i/64*2*Math.PI;return offsetCoordinates(origin,[radius*Math.sin(angle),radius*Math.cos(angle)]);});
    map.addSource(radiusSource,{type:'geojson',data:{type:'Feature',properties:{},geometry:{type:'Polygon',coordinates:[radiusRing]}}});
    map.addLayer({id:'campus-radius-fill',type:'fill',source:radiusSource,paint:{'fill-color':'#0052cc','fill-opacity':.08}},'building');
    map.addLayer({id:'campus-radius-edge',type:'line',source:radiusSource,paint:{'line-color':'#0052cc','line-width':1,'line-opacity':.55,'line-dasharray':[3,3]}},'waterway_line_label');
  }
  function highlight(id){
    selectedId=id;const map=window.streetMap.getMap();
    if(map?.getLayer('campus-demo-line'))map.setPaintProperty('campus-demo-line','line-color',['case',['==',['get','id'],id||''],'#ea6a12','#5f95d8']);
    nodes.forEach(marker=>marker.getElement().classList.toggle('is-selected',marker.getElement().dataset.campusId===id));
    $('campus-results').querySelectorAll('[data-campus-id]').forEach(button=>{const selected=button.dataset.campusId===id;button.classList.toggle('is-selected',selected);button.setAttribute('aria-pressed',String(selected));});
  }
  function sector(origin,radius,from,to,alpha){
    const points=[origin];
    for(let i=0;i<=6;i++){const angle=(from+(to-from)*i/6)*Math.PI/180;points.push(offsetCoordinates(origin,[radius*Math.sin(angle),radius*Math.cos(angle)]));}
    points.push(origin);
    return {type:'Feature',properties:{alpha},geometry:{type:'Polygon',coordinates:[points]}};
  }
  // A map layer, not a DOM overlay, so the sweep stays true to the search radius while the camera moves.
  // The cap keeps a slow tile server from holding the results back indefinitely.
  function mapSettled(map){
    if(!map.isMoving()&&map.areTilesLoaded())return Promise.resolve();
    return new Promise(resolve=>{
      const done=()=>{clearTimeout(limit);map.off('idle',done);resolve();};
      const limit=setTimeout(done,1800);
      map.once('idle',done);
    });
  }
  async function runSweep(origin,radius,request){
    const map=window.streetMap.getMap();
    await mapSettled(map);
    if(!active||request!==generation)return false;
    map.addSource(sweepSource,{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    map.addLayer({id:'campus-radius-sweep',type:'fill',source:sweepSource,paint:{'fill-color':'#0052cc','fill-opacity':['get','alpha'],'fill-antialias':false}},'building');
    return new Promise(resolve=>{
      const started=performance.now();
      const step=now=>{
        if(!active||request!==generation||!map.getSource(sweepSource))return resolve(false);
        const fraction=Math.min(1,(now-started)/2400), head=720*fraction, fade=fraction>.85?(1-fraction)/.15:1;
        const features=Array.from({length:10},(_,i)=>sector(origin,radius,head-(i+1)*9,head-i*9,.26*(1-i/10)*fade));
        map.getSource(sweepSource).setData({type:'FeatureCollection',features});
        if(fraction<1)return requestAnimationFrame(step);
        map.removeLayer('campus-radius-sweep');map.removeSource(sweepSource);resolve(true);
      };
      requestAnimationFrame(step);
    });
  }
  function fitAll(){
    const map=window.streetMap.getMap(),location=window.streetMap.getLocation();if(!map||!location)return;
    const bounds=new maplibregl.LngLatBounds(location.coordinates,location.coordinates);radiusRing.forEach(point=>bounds.extend(point));results.forEach(item=>bounds.extend(item.coordinates));
    map.fitBounds(bounds,{padding:{top:140,bottom:85,left:45,right:45},maxZoom:13,pitch:35,bearing:-15,duration:reduced?0:1000});
  }
  function updateBasket(){
    const summary=$('campus-basket-summary');
    summary.textContent=basket.size?'合作候選':'合作候選（0）';
    if(basket.size){const badge=node('span',basket.size,`campus-count${basket.size!==shownCount?' is-new':''}`);summary.append(badge);}
    shownCount=basket.size;
    const box=$('campus-basket-list');box.replaceChildren();
    if(!basket.size)box.append(node('p','尚未加入候選校區。'));
    basket.forEach(item=>{const row=node('div',null,'campus-basket-row');const info=node('div',null,'campus-basket-info');info.append(node('strong',item.institution_name));
      const direct=[...(item.matched_departments||[]),...(item.unlocated_department_matches||[])];
      const departments=direct.length?direct:(item.related_departments?.length?item.related_departments:item.departments);
      const seen=new Set();
      for(const dept of departments||[]){
        const key=dept.department_id||dept.name;if(!dept.name||seen.has(key))continue;seen.add(key);
        const unlocated=(item.unlocated_department_matches||[]).some(d=>(d.department_id||d.name)===key)||dept.location_status==='TEACHING_LOCATION_UNVERIFIED';
        const label=unlocated?'教學校區待核驗':dept.relation_label;
        info.append(node('span','科系：'+dept.name,'campus-basket-department'));
        if(label)info.append(node('small',label,'campus-basket-location'));
      }
      if(!seen.size)info.append(node('span','科系：資料待補（尚未取得符合科系）','campus-basket-department'));
      info.append(node('small','參考校區：'+item.name,'campus-basket-location'));
      row.append(info);const remove=node('button','移除');remove.type='button';remove.setAttribute('aria-label',`移除${campusName(item)}`);remove.addEventListener('click',()=>{basket.delete(item.id);updateBasket();updateAddButton();});row.append(remove);box.append(row);});
  }
  function updateAddButton(){
    const button=popupBox?.querySelector('.campus-add');if(!button)return;
    const added=basket.has(selectedId),name=popupBox.querySelector('h2').textContent;
    // ponytail: SVG icon instead of the full-width ＋/✓ glyphs, whose side bearings made the gap uneven.
    const icon=added?'<path d="M3 8.5l3.2 3L13 4.5"/>':'<path d="M8 3v10M3 8h10"/>';
    button.innerHTML=`<svg viewBox="0 0 16 16" aria-hidden="true">${icon}</svg>`;button.append(added?'已加入':'加入候選');button.classList.toggle('is-added',added);
    button.setAttribute('aria-pressed',String(added));button.setAttribute('aria-label',added?`${name}已加入合作候選，點擊移除`:`將${name}加入合作候選`);
  }
  function openSchool(item){
    const map=window.streetMap.getMap();if(!active||!map)return;
    closePopup({restore:false});window.streetMap.closeCompany(false);highlight(item.id);
    focusTrigger=document.activeElement;
    camera??=window.createCampusCamera(map,reduced);
    const box=node('section',null,'campus-school-popup');box.setAttribute('aria-label',campusName(item)+' 校區資訊');
    const head=node('div',null,'campus-popup-head');head.title='按住這裡拖曳卡片';
    head.append(node('span',`${academicYear} 學年度 · 官方名冊`,'campus-source-badge'));
    const close=node('button','×');close.type='button';close.className='campus-return';
    close.setAttribute('aria-label','關閉校區資訊並返回探索視角');
    close.addEventListener('click',()=>closePopup({focus:true}));head.append(close);
    popupBox=box;makeDraggable(box,head);
    const title=node('div',null,'campus-title-row');title.append(node('h2',item.institution_name));
    const add=node('button',null,'campus-add');add.type='button';add.addEventListener('click',()=>{if(basket.has(item.id))basket.delete(item.id);else basket.set(item.id,item);updateBasket();if(basket.has(item.id))panel.querySelector('.campus-basket').open=true;updateAddButton();status(basket.has(item.id)?`${campusName(item)}已加入合作候選，尚未聯絡。`:`已移除${campusName(item)}。`);});
    title.append(add);box.append(head,title,node('p',item.name));updateAddButton();
    const facts=node('dl');[['校區地址',item.address],['直線距離',item.distance_km.toFixed(1)+' 公里']].forEach(([title,value])=>facts.append(node('dt',title),node('dd',value)));box.append(facts);
    const phone=item.school_phone,phoneValue=node('dd',phone?.status==='AVAILABLE'&&phone.display?phone.display:'電話資料待補','campus-phone-number');
    facts.append(node('dt','學校總機'),phoneValue);
    const sources=node('div',null,'campus-official-links');
    if(phone?.status==='AVAILABLE'){
      const phoneMeta=node('p',null,'campus-data-note'),phoneSource=link('電話來源：教育部名錄 ↗',phone.source_url);
      if(phoneSource)phoneMeta.append(phoneSource);
      sources.append(phoneMeta);
    }
    const source=link('教育部校區來源 ↗',item.source_url),website=link('學校官方網站 ↗',item.website),coordinate=link('校區座標來源 ↗',item.coordinate_reference?.source_url);
    if(source)sources.append(source);if(website)sources.append(website);if(coordinate)sources.append(coordinate);
    const insights=node('section',null,'campus-insights');
    insights.setAttribute('aria-label','學校科系資訊');
    window.renderCampusDepartments(insights,item);
    box.append(insights,sources,node('p','距離由所選道路位置計算，非通勤距離。','campus-popup-note'));
    // Laid out off-screen first so the anchor is chosen from the card's real height.
    Object.assign(box.style,{position:'absolute',visibility:'hidden',width:'310px'});$('city-stage').append(box);
    // camera.focus centres the school (padding 90 top / 70 bottom), so pick the side from where it will land, not where it is now.
    const view=map.getContainer(),anchor=window.streetMap.popupAnchorAt(box,{x:view.clientWidth/2,y:view.clientHeight/2+10});
    Object.assign(box.style,{position:'',visibility:'',width:''});
    popup=new maplibregl.Popup({closeButton:false,closeOnClick:false,anchor,offset:23,maxWidth:'310px',focusAfterOpen:false}).setLngLat(item.coordinates).setDOMContent(box).addTo(map);
    $('city-stage').classList.add('campus-popup-open');popup.on('close',()=>{$('city-stage').classList.remove('campus-popup-open');highlight(null);});
    camera.focus(item.coordinates);
    close.focus({preventScroll:true});
  }
  function renderList(){
    const box=$('campus-results');box.replaceChildren();
    results.forEach(item=>{
      const button=node('button',null,'campus-result');
      button.type='button';button.dataset.campusId=item.id;button.setAttribute('aria-pressed','false');
      button.append(node('strong',item.institution_name),node('span',`${item.name} · ${item.district}`),
        node('small',`直線 ${item.distance_km.toFixed(1)} 公里 · ${academicYear} 學年度`));
      if(item.unlocated_department_matches?.length){
        button.append(node('span','同校有符合的科系，教學校區待核驗','campus-result-caution'));
      }
      if(item.match_reason)button.append(node('small',item.match_reason,item.match_tier==='RELATED'?'campus-result-caution':''));
      button.append(node('span','查看校區與科系資訊','campus-result-action'));
      button.addEventListener('click',()=>openSchool(item));box.append(button);
    });
  }
  function drawMap(location){
    const map=window.streetMap.getMap();if(!map||!results.length)return;
    const empty={type:'FeatureCollection',features:[]};
    map.addSource(lineSource,{type:'geojson',data:empty});map.addSource(headSource,{type:'geojson',data:empty});
    map.addLayer({id:'campus-demo-halo',type:'line',source:lineSource,paint:{'line-width':9,'line-color':'#8ebaff','line-opacity':.2,'line-blur':3}});
    map.addLayer({id:'campus-demo-line',type:'line',source:lineSource,paint:{'line-width':2.6,'line-color':'#5f95d8','line-opacity':.9,'line-dasharray':DASH_FRAMES[0]}});
    map.addLayer({id:'campus-demo-head',type:'circle',source:headSource,paint:{'circle-radius':4,'circle-color':'#e4f4ff','circle-stroke-color':'#80b4ee','circle-stroke-width':2,'circle-blur':.15}});
    nodes=results.map(item=>{const button=node('button',null,'campus-node');button.type='button';button.dataset.campusId=item.id;button.disabled=!reduced;button.setAttribute('aria-label',campusName(item)+'，查看校區資訊');button.innerHTML='<i></i><i></i><svg viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="10.5"/><path d="M18 2v9M18 25v9M2 18h9M25 18h9"/><circle cx="18" cy="18" r="2.6"/></svg>';button.append(node('span',campusName(item)));button.addEventListener('click',()=>openSchool(item));return new maplibregl.Marker({element:button,anchor:'center'}).setLngLat(item.coordinates).addTo(map);});
    const paths=results.map(item=>curve(location.coordinates,item.coordinates)),started=performance.now();
    function draw(now){
      if(!active||!map.getSource(lineSource))return;
      let done=true;const heads=[];
      const features=results.map((item,i)=>{const progress=reduced?1:Math.min(1,Math.max(0,(now-started-i*180)/1300));if(progress<1)done=false;const count=Math.max(2,Math.ceil(progress*64)+1);const points=paths[i].slice(0,count);if(progress>0&&progress<1)heads.push({type:'Feature',geometry:{type:'Point',coordinates:points.at(-1)},properties:{}});if(progress===1){nodes[i].getElement().classList.add('is-visible');nodes[i].getElement().disabled=false;}return {type:'Feature',properties:{id:item.id},geometry:{type:'LineString',coordinates:points}};});
      map.getSource(lineSource).setData({type:'FeatureCollection',features});map.getSource(headSource).setData({type:'FeatureCollection',features:heads});
      if(!done)frame=requestAnimationFrame(draw);else if(!reduced)flowLines(map);
    }
    draw(performance.now());fitAll();
  }
  async function refresh(sweep=false){
    if(popup)camera?.restore(true);
    cancelRequest();const request=generation;clearResults();busy(false);
    const location=window.streetMap.getLocation(),map=window.streetMap.getMap();
    if(!location||!map){status('等待所選道路定位完成；定位成功後會查詢真實校區。');return;}
    const nextOrigin=location.coordinates.join(',');
    if(originKey!==nextOrigin){basket.clear();originKey=nextOrigin;updateBasket();}
    const radiusInput=$('campus-radius'),radius=Number(radiusInput.value);
    if(!radiusInput.checkValidity()||!Number.isFinite(radius)||radius<.1){status('請輸入至少 0.1 公里的有效搜尋範圍。');return;}
    const params=new URLSearchParams({latitude:location.coordinates[1],longitude:location.coordinates[0],radius_km:radius,q:$('campus-query').value.trim(),include_related:$('campus-related').checked});
    const pending=new AbortController();controller=pending;let timedOut=false;
    const timeout=setTimeout(()=>{timedOut=true;pending.abort();},15000);
    status('正在查詢官方校區資料…');busy(true);
    try{
      const response=await fetch('/api/education/campuses?'+params,{signal:pending.signal,cache:'no-store'});
      if(!active||request!==generation)return;
      if(!response.ok)throw Error(response.status===503?'校區資料目前無法讀取，請確認教育資料庫後重新查詢。':response.status===422?'查詢條件無效，請確認名稱與搜尋範圍。':`校區查詢失敗（HTTP ${response.status}），請重新查詢。`);
      const data=await response.json();if(!active||request!==generation)return;
      results=readData(data);
      if(releaseId&&releaseId!==data.release_id){basket.clear();updateBasket();}
      releaseId=data.release_id;academicYear=data.academic_year;
      $('campus-source-label').textContent=`${academicYear} 學年度 · 官方名冊`;
      const expansion=data.query_expansion;
      const roles=data.career_query?.roles;
      const careerSearch=Array.isArray(roles)&&roles.length>0;
      const queryNote=careerSearch?`依「${roles.join('、')}」查詢系所職涯資料。 `:
        expansion?.alias_applied&&Array.isArray(expansion.department_terms)?`「${expansion.input}」以「${expansion.department_terms.join('、')}」查詢。 `:'';
      updateBasket();drawRadius(location.coordinates,radius);
      const sweepKey=[nextOrigin,radius,params.get('q'),params.get('include_related')].join('|');
      if(sweep&&!reduced&&sweepKey!==lastSweep){
        fitAll();
        if(!await runSweep(location.coordinates,radius,request))return;
        lastSweep=sweepKey;
      }
      renderList();
      (data.suggestions||[]).forEach(name=>{const b=node('button','試試：'+name);b.type='button';b.addEventListener('click',()=>{$('campus-query').value=name;refresh(true);});$('campus-suggestions').append(b);});
      if(!results.length){
        status(queryNote+(careerSearch
          ? '範圍內沒有符合的職涯資料。可擴大範圍、勾選相關領域或試試其他職務名稱。'
          : '範圍內找不到符合的校區。可擴大範圍，或改用常見職務名稱、學校或系所全名。'));
        fitAll();return;
      }
      status(queryNote+`找到 ${results.length} 個校區，指定學校優先，再依直接符合與距離排序。校區與系所關聯仍有待核驗項目，詳見個別來源。`);drawMap(location);
    }catch(error){
      if(!active||request!==generation)return;
      clearResults();status(timedOut?'校區查詢逾時，請重新查詢。':error.name==='AbortError'?'查詢已取消，可重新查詢。':error.message||'無法連線至校區服務，請重新查詢。');$('campus-retry').hidden=false;
    }finally{clearTimeout(timeout);if(request===generation){controller=null;busy(false);}}
  }
  function activate(){active=true;workspace.classList.add('campus-active');tabs.hidden=false;context.hidden=false;window.radarFeatures.select('校園人才媒合');window.streetMap.closeCompany(false);selectView('schools');refresh(true);}
  function deactivate(){if(!active)return;active=false;if(popup)camera?.restore(true);cancelRequest();clearResults();busy(false);workspace.classList.remove('campus-active');tabs.hidden=true;context.hidden=true;panel.hidden=true;chat.hidden=false;window.radarFeatures.select(null);}
  window.campusMatching={toggle(){active?deactivate():activate();},deactivate};
  $('campus-filters').addEventListener('submit',event=>{event.preventDefault();refresh(true);});
  $('campus-retry').addEventListener('click',()=>refresh(true));
  $('campus-exit').addEventListener('click',deactivate);$('campus-show-all').addEventListener('click',()=>{if(popup)camera?.discard();closePopup({restore:false});fitAll();});
  document.addEventListener('streetmap:location',()=>{if(active)refresh();});
  document.addEventListener('streetmap:location-changing',()=>{if(active){if(popup)camera?.discard();cancelRequest();clearResults();busy(false);basket.clear();originKey='';updateBasket();status('正在切換探索地點，定位完成後重新查詢校區…');}});
  document.addEventListener('streetmap:location-error',event=>{if(active)status(event.detail+' 校園地圖需先完成道路定位，請使用地圖重試。');});
  document.addEventListener('streetmap:company-open',()=>{if(popup)camera?.discard();closePopup({restore:false});});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&popup&&!document.querySelector('dialog[open]'))closePopup({focus:true});});
  updateBasket();
})();
