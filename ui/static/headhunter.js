/* Headhunter workbench on the map. Everything here is a labelled mock: no site is contacted. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const workspace = document.querySelector('.radar-workspace'), stage = $('city-stage');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  // ponytail: fixed demo script; connectStream below is the only part an EventSource has to replace.
  const MOCK_EVENTS = [
    {at:400, site:'104', percent:15, state:'正在開啟 104', url:'https://www.104.com.tw/jobs/search', log:'[INFO] Selecting target site: 104'},
    {at:1500, site:'104', percent:30, state:'正在 104 辨識驗證碼', log:'[WARNING] Captcha Detected. Invoking Solver...', tone:'warn', row:0},
    {at:3000, site:'104', percent:45, state:'正在 104 搜尋人才', log:'[SUCCESS] Captcha Bypassed (0.4s)', tone:'ok', row:1},
    {at:4600, site:'104', percent:65, state:'正在 104 解析人才', log:'[SUCCESS] 3 candidates captured', tone:'ok', row:4, scroll:110, people:[
      {name:'林XX',summary:'5 年 CNC 經驗 / 台中大雅',district:'大雅區',fit:'符合',reason:'車床與品檢經驗符合 CNC 技術員需求。'},
      {name:'張XX',summary:'4 年品管經驗 / 台中西屯',district:'西屯區',fit:'符合',reason:'品管與量測經驗可對應需求。'},
      {name:'黃XX',summary:'2 年 CNC 經驗 / 台中潭子',district:'潭子區',fit:'部分符合',reason:'有基本操作經驗，年資較短。'}]},
    {at:6200, site:'1111', percent:78, state:'正在 1111 搜尋人才', url:'https://www.1111.com.tw/search/job', log:'[SUCCESS] 3 candidates captured', tone:'ok', row:2, scroll:0, people:[
      {name:'吳XX',summary:'6 年機械維修經驗 / 台中太平',district:'太平區',fit:'符合',reason:'設備保養經驗與職缺相關。'},
      {name:'蔡XX',summary:'3 年銑床經驗 / 台中大里',district:'大里區',fit:'部分符合',reason:'銑床經驗相關，未見車床經驗。'},
      {name:'劉XX',summary:'1 年操作員經驗 / 台中烏日',district:'烏日區',fit:'部分符合',reason:'僅有基礎機台操作經驗。'}]},
    {at:7600, site:'LinkedIn', percent:88, state:'正在 LinkedIn 搜尋人才', url:'https://www.linkedin.com/search/results/people', log:'[INFO] Switching site: LinkedIn', row:6, scroll:150},
    {at:8200, site:'LinkedIn', failed:true, percent:90, state:'LinkedIn 驗證失敗，換下一家網站', log:'[ERROR] Captcha failed on LinkedIn. Trying next site...', tone:'err'},
    {at:8900, site:'CakeResume', percent:96, state:'正在 CakeResume 搜尋人才', url:'https://www.cake.me/resumes', log:'[SUCCESS] 2 candidates captured', tone:'ok', row:1, scroll:0, people:[
      {name:'鄭XX',summary:'8 年製程工程經驗 / 台中南屯',district:'南屯區',fit:'符合',reason:'製程改善經驗與需求高度相關。'},
      {name:'謝XX',summary:'2 年品管經驗 / 台中豐原',district:'豐原區',fit:'部分符合',reason:'品檢經驗相關，非 CNC 操作。'}]},
    {at:10200, percent:100, state:'任務完成', tone:'ok', people:[
      {name:'陳XX',summary:'3 年 CNC 經驗 / 台中太平',district:'太平區',fit:'部分符合',reason:'有 CNC 經驗，需再確認車床能力。'},
      {name:'王XX',summary:'7 年機械加工經驗 / 台中神岡',district:'神岡區',fit:'部分符合',reason:'加工經驗豐富，需再確認 CNC 操作。'}]},
  ];
  const left = document.createElement('aside'), right = document.createElement('aside');
  left.className = 'hunter-side hunter-left';left.setAttribute('aria-label','獵頭 Agent 任務與紀錄');left.inert = true;
  right.className = 'hunter-side hunter-right';right.setAttribute('aria-label','獵頭 Agent 瀏覽器與人才清單');right.inert = true;
  const siteChip = (name,checked) => `<label class="hunter-site" data-site="${name}"><input type="checkbox"${checked ? ' checked' : ''}><i></i>${name}</label>`;
  left.innerHTML = `<section class="hunter-pane hunter-head"><strong>獵頭 Agent 戰情室</strong><span class="hunter-mode">展示資料・模擬流程</span><button class="hunter-pill" id="hunter-sound" type="button"></button><button class="hunter-pill" id="hunter-exit" type="button">退出</button></section>
    <section class="hunter-pane"><h3>1. 任務發起面板</h3><div class="hunter-body">
      <label class="hunter-field">職缺<input type="text" id="hunter-job" value="CNC 技術員"></label>
      <span class="hunter-tag" id="hunter-tag">CNC 技術員</span>
      <div class="hunter-field">目標網站<div class="hunter-sites">${['104','1111','LinkedIn','CakeResume'].map(name => siteChip(name,true)).join('')}${['GitHub','國科會'].map(name => siteChip(name,false)).join('')}</div></div>
      <p class="hunter-progress"><span>進度</span><span id="hunter-percent">0%</span></p>
      <div class="hunter-track" role="progressbar" aria-label="任務進度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" id="hunter-track"><div class="hunter-fill" id="hunter-fill"></div></div>
      <p class="hunter-state" id="hunter-state" role="status">目前狀態：等待發起任務</p>
      <button class="hunter-start" id="hunter-start" type="button">開始任務</button>
    </div></section>
    <section class="hunter-pane hunter-grow"><h3>3. 實時思維鏈（CoT）與錯誤排除</h3><div class="hunter-body hunter-terminal" id="hunter-terminal"><ol class="hunter-log" id="hunter-log" aria-live="off"></ol><div class="hunter-prompt">&gt; </div></div></section>`;
  right.innerHTML = `<section class="hunter-pane hunter-grow"><h3>2. Agent 即時實況虛擬瀏覽器</h3>
      <div class="hunter-url"><i></i><i></i><i></i><span id="hunter-url">about:blank</span></div>
      <div class="hunter-screen" id="hunter-screen" aria-hidden="true"><div class="hunter-feed" id="hunter-feed"></div><div class="hunter-scan"></div><i class="hunter-cursor" id="hunter-cursor"></i><div class="hunter-flag">AI OPERATING...</div><div class="hunter-sim">Computer Use 模擬操作中</div></div></section>
    <section class="hunter-pane hunter-grow"><h3>4. 已捕獲人才即時快顯<span class="hunter-count" id="hunter-count">0 位</span><select class="hunter-view" id="hunter-view" aria-label="排序與篩選"><option value="latest">最新優先</option><option value="fit">符合優先</option><option value="strong">只看符合</option></select></h3>
      <div class="hunter-body hunter-list" id="hunter-list"></div><p class="hunter-note">地圖標記為行政區中心示意，非住址。</p></section>`;
  stage.append(left,right);
  // Uneven line widths so the placeholder reads like a real profile list.
  const skeleton = [[58,84,41],[47,72],[66,91,33],[39,63],[71,78,52],[52,88],[44,69,37],[63,76],[49,82,28]]
    .map(lines => `<div class="hunter-row"><b></b><div>${lines.map(width => `<span style="width:${width}%"></span>`).join('')}</div></div>`).join('');
  // The second copy makes the -50% marquee loop seamless.
  $('hunter-feed').innerHTML = skeleton + skeleton;
  const rows = [...$('hunter-feed').children].slice(0,9), sites = [...left.querySelectorAll('.hunter-site')];
  const sweepSource = 'hunter-sweep', linkSource = 'hunter-links', radiusSource = 'hunter-radius';
  // Same dash stepping as campus matching: MapLibre has no dash offset to animate.
  const DASH_FRAMES = [[0,4,3],[.5,4,2.5],[1,4,2],[1.5,4,1.5],[2,4,1],[2.5,4,.5],[3,4,0],[0,.5,3,3.5],[0,1,3,3],[0,1.5,3,2.5],[0,2,3,2],[0,2.5,3,1.5],[0,3,3,1],[0,3.5,3,.5]];
  let active = false, collapsedSidebar = false, movedMap = false, centres = null, sweepEnd = 0, links = [], linkFrame = 0, flowFrame = 0, selectedId = null, focusId = null;
  let audio, soundOn = true, typing = Promise.resolve(), run = 0, timers = [], scrolled = 0, captured = [];
  try { soundOn = localStorage.getItem('radar-sound') !== 'off'; } catch {}

  function syncSound() {
    $('hunter-sound').textContent = soundOn ? '音效：開' : '音效：關';$('hunter-sound').setAttribute('aria-pressed',String(soundOn));
  }
  function unlockAudio() {
    if(!soundOn || !window.AudioContext)return;
    audio ??= new AudioContext();
    if(audio.state === 'suspended')audio.resume();
  }
  function playCapture() {
    if(!soundOn || !audio)return;
    const now = audio.currentTime;
    [[1320,0],[1980,.07]].forEach(([frequency,delay]) => {
      const osc = audio.createOscillator(), gain = audio.createGain(), start = now + delay;
      osc.frequency.value = frequency;
      gain.gain.setValueAtTime(.001,start);gain.gain.exponentialRampToValueAtTime(.08,start + .006);gain.gain.exponentialRampToValueAtTime(.001,start + .16);
      osc.connect(gain);gain.connect(audio.destination);
      osc.onended = () => gain.disconnect();
      osc.start(start);osc.stop(start + .17);
    });
  }
  // Mock people have no address, so markers sit near a district's centre instead of inventing one.
  async function loadCentres() {
    if(centres)return centres;
    const response = await fetch('/static/taichung-districts.geojson');
    if(!response.ok)throw Error('district boundaries unavailable');
    const data = await response.json();
    centres = Object.fromEntries(data.features.map(feature => {
      const {type,coordinates} = feature.geometry;
      const ring = type === 'Polygon' ? coordinates[0] : coordinates.reduce((big,part) => part[0].length > big.length ? part[0] : big,[]);
      const total = ring.reduce((sum,[lng,lat]) => [sum[0] + lng,sum[1] + lat],[0,0]);
      return [feature.properties.TOWNNAME,[total[0] / ring.length,total[1] / ring.length]];
    }));
    return centres;
  }
  function ensureLayers(map) {
    if(map.getSource(sweepSource))return;
    const empty = {type:'FeatureCollection',features:[]};
    [sweepSource,linkSource,radiusSource].forEach(id => map.addSource(id,{type:'geojson',data:empty}));
    map.addLayer({id:'hunter-radius-fill',type:'fill',source:radiusSource,paint:{'fill-color':'#0052cc','fill-opacity':.08}},'building');
    map.addLayer({id:'hunter-sweep',type:'fill',source:sweepSource,paint:{'fill-color':'#0052cc','fill-opacity':['get','alpha'],'fill-antialias':false}},'building');
    map.addLayer({id:'hunter-radius-edge',type:'line',source:radiusSource,paint:{'line-color':'#0052cc','line-width':1,'line-opacity':.55,'line-dasharray':[3,3]}},'waterway_line_label');
    map.addLayer({id:'hunter-links-halo',type:'line',source:linkSource,paint:{'line-width':9,'line-color':'#8ebaff','line-opacity':.2,'line-blur':3}},'waterway_line_label');
    map.addLayer({id:'hunter-links',type:'line',source:linkSource,paint:{'line-width':2.6,'line-color':'#5f95d8','line-opacity':.9,'line-dasharray':DASH_FRAMES[0]}},'waterway_line_label');
  }
  function clearLayers() {
    const map = window.streetMap.getMap();
    cancelAnimationFrame(linkFrame);cancelAnimationFrame(flowFrame);links = [];sweepEnd = 0;selectedId = null;focusId = null;
    if(!map)return;
    ['hunter-sweep','hunter-links','hunter-links-halo','hunter-radius-fill','hunter-radius-edge'].forEach(id => {if(map.getLayer(id))map.removeLayer(id);});
    [sweepSource,linkSource,radiusSource].forEach(id => {if(map.getSource(id))map.removeSource(id);});
  }
  function flowLinks(map) {
    if(reduced)return;
    let shown = -1;
    cancelAnimationFrame(flowFrame);
    const step = now => {
      if(!active || !map.getLayer('hunter-links'))return;
      const index = Math.floor(now / 75) % DASH_FRAMES.length;
      if(index !== shown){shown = index;map.setPaintProperty('hunter-links','line-dasharray',DASH_FRAMES[index]);}
      flowFrame = requestAnimationFrame(step);
    };
    flowFrame = requestAnimationFrame(step);
  }
  function paintLinks() {
    const map = window.streetMap.getMap();
    if(!map?.getLayer('hunter-links'))return;
    const lit = [...new Set([selectedId,focusId].filter(id => id !== null))];
    map.setPaintProperty('hunter-links','line-color',lit.length ? ['match',['get','id'],lit,'#ea6a12','#5f95d8'] : '#5f95d8');
  }
  function offset([lng,lat],east,north) {
    return [lng + east / (111.32 * Math.cos(lat * Math.PI / 180)),lat + north / 110.57];
  }
  function sector(origin,radius,from,to,alpha) {
    const points = [origin];
    for(let i = 0;i <= 6;i++) {
      const angle = (from + (to - from) * i / 6) * Math.PI / 180;
      points.push(offset(origin,radius * Math.sin(angle),radius * Math.cos(angle)));
    }
    points.push(origin);
    return {type:'Feature',properties:{alpha},geometry:{type:'Polygon',coordinates:[points]}};
  }
  // One turn every 1.2s; the sweep covers every district a candidate can appear in.
  function runSweep(map,origin) {
    const reach = Math.max(...Object.values(centres).map(([lng,lat]) => Math.hypot((lng - origin[0]) * 111.32 * Math.cos(origin[1] * Math.PI / 180),(lat - origin[1]) * 110.57)));
    const radius = reach * 1.05, current = run, started = performance.now();
    const ring = Array.from({length:65},(_,i) => {const angle = i / 64 * 2 * Math.PI;return offset(origin,radius * Math.sin(angle),radius * Math.cos(angle));});
    map.getSource(radiusSource).setData({type:'Feature',properties:{},geometry:{type:'Polygon',coordinates:[ring]}});
    const step = now => {
      if(!active || current !== run || !map.getSource(sweepSource))return;
      const fade = sweepEnd ? Math.max(0,1 - (now - sweepEnd) / 600) : 1, head = (now - started) / 1200 * 360;
      map.getSource(sweepSource).setData({type:'FeatureCollection',features:fade ? Array.from({length:10},(_,i) => sector(origin,radius,head - (i + 1) * 9,head - i * 9,.26 * (1 - i / 10) * fade)) : []});
      if(fade)requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  function drawLinks() {
    const map = window.streetMap.getMap();
    if(!map?.getSource(linkSource))return;
    cancelAnimationFrame(linkFrame);
    const step = now => {
      if(!map.getSource(linkSource))return;
      let moving = false;
      const features = links.filter(link => !link.item.card.hidden).map(link => {
        const progress = reduced ? 1 : Math.min(1,(now - link.started) / 520);
        if(progress < 1)moving = true;
        const end = link.from.map((value,axis) => value + (link.to[axis] - value) * (1 - Math.pow(1 - progress,3)));
        return {type:'Feature',properties:{id:link.item.id},geometry:{type:'LineString',coordinates:[link.from,end]}};
      });
      map.getSource(linkSource).setData({type:'FeatureCollection',features});
      if(moving)linkFrame = requestAnimationFrame(step);
    };
    linkFrame = requestAnimationFrame(step);
  }
  function selectPerson(item) {
    const opening = item && !item.card.classList.contains('is-selected');
    selectedId = opening ? item.id : null;
    captured.forEach(other => {
      const on = opening && other === item;
      other.card.classList.toggle('is-selected',on);
      other.more.hidden = !on;
      other.button.setAttribute('aria-expanded',String(on));
      other.marker?.getElement().classList.toggle('is-selected',on);
    });
    paintLinks();
    if(!opening)return;
    item.card.scrollIntoView({block:'nearest',behavior:reduced ? 'auto' : 'smooth'});
    const map = window.streetMap.getMap();
    // The offset centres the point in the gap between the two side panels.
    if(map && item.point)map.flyTo({center:item.point,zoom:Math.max(map.getZoom(),13),offset:[(left.offsetWidth - right.offsetWidth) / 2,0],duration:reduced ? 0 : 900,essential:false});
  }
  function focusPerson(item) {
    focusId = item ? item.id : null;
    captured.forEach(other => other.marker?.getElement().classList.toggle('is-focus',other === item));
    paintLinks();
  }
  function addMarker(item,person,index) {
    const map = window.streetMap.getMap(), centre = centres?.[person.district];
    if(!map || !centre)return;
    const button = document.createElement('button');
    button.className = 'campus-node hunter-node';button.type = 'button';
    button.setAttribute('aria-label',`${person.name}，${person.district}中心示意，查看候選人`);
    button.innerHTML = '<i></i><i></i><svg viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="10.5"/><path d="M18 2v9M18 25v9M2 18h9M25 18h9"/><circle cx="18" cy="18" r="2.6"/></svg>';
    button.append(piece('span','',person.name));
    requestAnimationFrame(() => button.classList.add('is-visible'));
    button.addEventListener('click',() => selectPerson(item));
    button.addEventListener('pointerenter',() => focusPerson(item));
    button.addEventListener('pointerleave',() => focusPerson(null));
    // A small spread keeps two people in one district from stacking exactly.
    const spread = (index % 4) * .006;
    const point = [centre[0] + spread,centre[1] + spread];
    item.point = point;
    item.marker = new maplibregl.Marker({element:button,anchor:'center'}).setLngLat(point).addTo(map);
    const origin = window.streetMap.getLocation()?.coordinates;
    if(origin){links.push({from:origin,to:point,started:performance.now(),item});drawLinks();}
  }
  function applyView() {
    const view = $('hunter-view').value;
    // CSS order rearranges cards without moving the DOM, so the entrance animation never replays.
    captured.forEach(({card,fit,marker},index) => {
      const hide = view === 'strong' && fit !== '符合';
      card.style.order = view === 'fit' ? (fit === '符合' ? 0 : 100) - index : -index;
      card.hidden = hide;
      if(marker)marker.getElement().hidden = hide;
    });
    drawLinks();
    const shown = captured.filter(item => !item.card.hidden).length;
    $('hunter-count').textContent = view === 'strong' ? `${shown}／${captured.length} 位` : `${captured.length} 位`;
  }
  function piece(tag,className,text) {
    const element = document.createElement(tag);element.className = className;
    if(text !== undefined)element.textContent = text;
    return element;
  }
  function addPerson(person) {
    const list = $('hunter-list');list.querySelector('.hunter-empty')?.remove();
    const card = piece('article','hunter-card');
    const fit = piece('p',`hunter-fit${person.fit === '符合' ? ' is-strong' : ''}`,person.fit);
    const button = piece('button','hunter-detail','查看評估');button.type = 'button';button.setAttribute('aria-expanded','false');
    const more = piece('div','hunter-more');more.hidden = true;
    more.append(piece('p','',`判斷理由：${person.reason}`),piece('p','','依據：公開個人頁（展示資料）'));
    card.append(piece('p','hunter-who',`候選人：${person.name}`),fit,piece('p','hunter-summary',person.summary),button,more);
    list.append(card);
    const item = {id:captured.length,card,fit:person.fit,more,button,marker:null,point:null};
    card.addEventListener('click',() => selectPerson(item));
    card.addEventListener('pointerenter',() => focusPerson(item));
    card.addEventListener('pointerleave',() => focusPerson(null));
    card.addEventListener('focusin',() => focusPerson(item));
    card.addEventListener('focusout',() => focusPerson(null));
    addMarker(item,person,captured.length);
    captured.push(item);applyView();
  }
  const pad = value => String(value).padStart(2,'0');
  function addLog(text,tone) {
    const now = new Date(), item = document.createElement('li'), stamp = document.createElement('time');
    stamp.textContent = `[${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}]`;
    item.append(stamp,'');if(tone)item.className = tone;
    const line = item.lastChild, current = run;
    // Lines queue up so a slow line never overlaps the next one.
    typing = typing.then(() => new Promise(done => {
      if(current !== run)return done();
      $('hunter-log').append(item);
      if(reduced){line.data = text;$('hunter-terminal').scrollTop = 1e6;return done();}
      // Paced by elapsed time so a busy map thread cannot leave the log trailing the cards.
      const begun = performance.now();
      const next = () => {
        if(current !== run)return done();
        const shown = Math.min(text.length,Math.ceil((performance.now() - begun) / 8) + 1);
        line.data = text.slice(0,shown);$('hunter-terminal').scrollTop = 1e6;
        if(shown < text.length)setTimeout(next,8);else done();
      };
      next();
    }));
  }
  function setProgress(percent) {
    $('hunter-fill').style.width = percent + '%';$('hunter-percent').textContent = percent + '%';$('hunter-track').setAttribute('aria-valuenow',percent);
  }
  function markSite(name,failed) {
    sites.forEach(site => {
      if(site.classList.contains('is-failed'))return;
      const here = site.dataset.site === name, wasActive = site.classList.contains('is-active');
      if(here && failed){site.classList.remove('is-active');site.classList.add('is-failed');return;}
      site.classList.toggle('is-active',here);
      if(wasActive && !here)site.classList.add('is-done');
    });
  }
  function switchPage(url) {
    if($('hunter-url').textContent === url)return;
    $('hunter-url').textContent = url;
    const screen = $('hunter-screen');
    screen.classList.remove('glitch');void screen.offsetWidth;screen.classList.add('glitch');
    timers.push(setTimeout(() => screen.classList.remove('glitch'),520));
  }
  function clickAt(x,y) {
    const ripple = piece('i','hunter-ripple');
    ripple.style.left = x + 'px';ripple.style.top = y + 'px';
    ripple.addEventListener('animationend',() => ripple.remove());
    $('hunter-screen').append(ripple);
  }
  // Every screen update goes through here, one event at a time.
  function handleEvent(step) {
    setProgress(step.percent);$('hunter-state').textContent = '目前狀態：' + step.state;
    if(step.url)switchPage(step.url);
    const total = captured.length + (step.people?.length ?? 0);
    addLog(step.percent === 100 ? `[SUCCESS] Run complete: ${total} candidates captured` : step.log,step.tone);
    (step.people || []).forEach((person,index) => {
      if(reduced)addPerson(person);
      else timers.push(setTimeout(() => addPerson(person),index * 100));
    });
    if(step.people)playCapture();
    markSite(step.site,step.failed);
    if(reduced) {
      rows.forEach((row,index) => row.classList.toggle('hot',index === step.row));
      if(step.scroll !== undefined)$('hunter-feed').style.transform = `translateY(${-step.scroll}px)`;
    }
    if(step.row !== undefined) {
      // The marquee moves the rows, so the pointer aims at fixed spots instead of a row.
      const x = 60, y = reduced ? rows[step.row].offsetTop - (step.scroll ?? scrolled) + 18 : 22 + step.row * 34;
      scrolled = step.scroll ?? scrolled;
      $('hunter-cursor').style.left = x + 'px';$('hunter-cursor').style.top = y + 'px';
      timers.push(setTimeout(() => clickAt(x + 6,y + 6),reduced ? 0 : 560));
    }
    if(step.percent === 100) {
      $('hunter-screen').classList.remove('running');left.classList.remove('is-hunting');$('hunter-start').disabled = false;
      sweepEnd = performance.now();
    }
  }
  function reset() {
    timers.forEach(clearTimeout);timers = [];scrolled = 0;run += 1;
    captured.forEach(item => item.marker?.remove());captured = [];clearLayers();left.classList.remove('is-hunting');
    $('hunter-count').textContent = '0 位';$('hunter-log').replaceChildren();
    $('hunter-list').replaceChildren(piece('p','hunter-empty','尚未捕獲人才。'));
    setProgress(0);$('hunter-url').textContent = 'about:blank';
    $('hunter-feed').style.transform = '';rows.forEach(row => row.classList.remove('hot'));
    sites.forEach(site => site.classList.remove('is-active','is-done','is-failed'));
    $('hunter-screen').classList.remove('glitch','running');
    $('hunter-start').disabled = false;$('hunter-state').textContent = '目前狀態：等待發起任務';
  }
  function fitCandidates() {
    const map = window.streetMap.getMap();if(!map || !centres)return;
    const bounds = new maplibregl.LngLatBounds();
    MOCK_EVENTS.flatMap(step => step.people || []).forEach(person => {if(centres[person.district])bounds.extend(centres[person.district]);});
    if(bounds.isEmpty())return;
    const box = stage.getBoundingClientRect(), wide = box.width > 900;
    map.fitBounds(bounds,{padding:wide ? {top:70,bottom:70,left:360,right:420} : 40,maxZoom:12.5,pitch:30,bearing:0,duration:reduced ? 0 : 1000});
    movedMap = true;
  }
  function connectStream(chosen) {
    const steps = MOCK_EVENTS.filter(step => !step.site || chosen.has(step.site));
    if(reduced){steps.forEach(handleEvent);return;}
    steps.forEach(step => timers.push(setTimeout(() => handleEvent(step),step.at)));
  }
  async function start() {
    reset();unlockAudio();$('hunter-start').disabled = true;$('hunter-start').textContent = '重新開始';
    $('hunter-state').textContent = '目前狀態：任務啟動中';$('hunter-screen').classList.add('running');left.classList.add('is-hunting');
    const current = run;
    // The panels still run without the map layer if the boundary file fails to load.
    try { await loadCentres(); } catch {}
    if(!active || current !== run)return;
    fitCandidates();
    const map = window.streetMap.getMap(), origin = window.streetMap.getLocation()?.coordinates;
    if(map && centres) {
      ensureLayers(map);flowLinks(map);
      if(origin && !reduced)runSweep(map,origin);
    }
    connectStream(new Set(sites.filter(site => site.querySelector('input').checked).map(site => site.dataset.site)));
  }
  function setSidebar(collapse) {
    const collapsed = workspace.classList.contains('sidebar-collapsed');
    if(collapsed === collapse)return;
    // Switched without its transition so the map only has to resize once.
    workspace.classList.add('sidebar-instant');
    $('sidebar-toggle').click();
    requestAnimationFrame(() => requestAnimationFrame(() => workspace.classList.remove('sidebar-instant')));
  }
  function activate() {
    active = true;
    window.streetMap.closeCompany(false);
    collapsedSidebar = !workspace.classList.contains('sidebar-collapsed');
    setSidebar(true);
    workspace.classList.add('hunter-active');left.inert = false;right.inert = false;
    window.radarFeatures.select('獵頭Agent');
    $('hunter-job').focus({preventScroll:true});
  }
  function deactivate(keepCamera = false) {
    if(!active)return;
    active = false;reset();$('hunter-start').textContent = '開始任務';
    workspace.classList.remove('hunter-active');left.inert = true;right.inert = true;
    if(collapsedSidebar)setSidebar(false);
    if(movedMap && !keepCamera)$('map-home').click();
    movedMap = false;
    window.radarFeatures.select(null);
  }
  $('hunter-start').addEventListener('click',start);
  $('hunter-exit').addEventListener('click',() => deactivate());
  $('hunter-view').addEventListener('change',applyView);
  $('hunter-job').addEventListener('input',event => {$('hunter-tag').textContent = event.target.value.trim() || '未填職缺';});
  $('hunter-sound').addEventListener('click',() => {
    soundOn = !soundOn;syncSound();
    try { localStorage.setItem('radar-sound',soundOn ? 'on' : 'off'); } catch {}
    unlockAudio();playCapture();
  });
  syncSound();reset();
  window.headhunter = {toggle(){active ? deactivate() : activate();},deactivate};
})();
