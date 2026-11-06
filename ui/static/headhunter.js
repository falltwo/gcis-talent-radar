/* Headhunter workbench on the map. Runs PR #24's sourcing API when the server has it; otherwise plays a labelled mock. */
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
      <p class="hunter-scope" id="hunter-scope" hidden><strong>適用職缺：</strong>軟體、AI／資料、設計、研究等會在網路上公開作品的職類。製程、設備、品保、生管、CNC 等製造業職缺在這些網站上很少有公開作品，通常找不到人；請改用「校園人才媒合」找相關科系，或用「刊登召募」刊登職缺。</p>
      <label class="hunter-field" id="hunter-max-field" hidden>要找幾位（1～20，每位約 4 秒）<input type="number" id="hunter-max" min="1" max="20" step="1" value="10" inputmode="numeric"></label>
      <details class="hunter-field hunter-sites-details"><summary>目標網站<span>展開／收合</span></summary><div class="hunter-sites">${['104','1111','LinkedIn','CakeResume'].map(name => siteChip(name,true)).join('')}${['GitHub','國科會'].map(name => siteChip(name,false)).join('')}</div></details>
      <p class="hunter-progress"><span>進度</span><span id="hunter-percent">0%</span></p>
      <div class="hunter-track" role="progressbar" aria-label="任務進度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" id="hunter-track"><div class="hunter-fill" id="hunter-fill"></div></div>
      <p class="hunter-state" id="hunter-state" role="status">目前狀態：等待發起任務</p>
    </div><div class="hunter-actions"><button class="hunter-start" id="hunter-start" type="button">開始任務</button></div></section>
    <section class="hunter-pane hunter-grow"><h3>3. 實時思維鏈（CoT）與錯誤排除</h3><div class="hunter-body hunter-terminal" id="hunter-terminal"><ol class="hunter-log" id="hunter-log" aria-live="off"></ol><div class="hunter-prompt">&gt; </div></div></section>`;
  right.innerHTML = `<section class="hunter-pane hunter-grow hunter-browser"><h3>2. Agent 即時實況虛擬瀏覽器<button class="hunter-pill hunter-zoom" id="hunter-zoom" type="button" aria-pressed="false">放大</button></h3>
      <div class="hunter-url"><i></i><i></i><i></i><span id="hunter-url">about:blank</span></div>
      <div class="hunter-screen" id="hunter-screen" aria-hidden="true"><div class="hunter-feed" id="hunter-feed"></div><div class="hunter-scan"></div><i class="hunter-cursor" id="hunter-cursor"></i><div class="hunter-flag">AI OPERATING...</div><div class="hunter-sim">Computer Use 模擬操作中</div></div></section>
    <section class="hunter-pane hunter-grow"><h3>4. 已捕獲人才即時快顯<span class="hunter-count" id="hunter-count">0 位</span><select class="hunter-view" id="hunter-view" aria-label="排序與篩選"><option value="latest">最新優先</option><option value="fit">符合優先</option><option value="strong">只看符合</option></select></h3>
      <div class="hunter-body hunter-list" id="hunter-list"></div><p class="hunter-note">地圖標記為行政區中心示意，非住址。</p></section>`;
  // While a run is on, the browser moves into the gap between the side panels; the map has nothing there yet.
  const center = document.createElement('aside');
  center.className = 'hunter-side hunter-center';center.setAttribute('aria-label','獵頭 Agent 放大的虛擬瀏覽器');center.inert = true;
  stage.append(left,center,right);
  const browser = right.querySelector('.hunter-browser'), roomy = matchMedia('(min-width: 901px)');
  let big = false;
  function setBig(on) {
    on = on && roomy.matches;
    if(on === big)return;
    big = on;
    // FLIP: measure, move, then animate from the old box so it glides instead of jumping.
    const from = browser.getBoundingClientRect();
    (on ? center : right).prepend(browser);
    workspace.classList.toggle('hunter-big',on);center.inert = !on;
    const to = browser.getBoundingClientRect();
    if(!reduced && to.width && from.width)browser.animate([
      {transformOrigin:'0 0',transform:`translate(${from.left - to.left}px,${from.top - to.top}px) scale(${from.width / to.width},${from.height / to.height})`},
      {transformOrigin:'0 0',transform:'none'}],{duration:400,easing:'cubic-bezier(.16,1,.3,1)'});
    $('hunter-zoom').textContent = on ? '縮小' : '放大';$('hunter-zoom').setAttribute('aria-pressed',String(on));
  }
  // Uneven line widths so the placeholder reads like a real profile list.
  const skeleton = [[58,84,41],[47,72],[66,91,33],[39,63],[71,78,52],[52,88],[44,69,37],[63,76],[49,82,28]]
    .map(lines => `<div class="hunter-row"><b></b><div>${lines.map(width => `<span style="width:${width}%"></span>`).join('')}</div></div>`).join('');
  // The second copy makes the -50% marquee loop seamless.
  $('hunter-feed').innerHTML = skeleton + skeleton;
  const frame = new Image();frame.className = 'hunter-frame';frame.alt = '';frame.hidden = true;
  $('hunter-screen').prepend(frame);
  frame.addEventListener('load',() => $('hunter-screen').style.setProperty('--frame-ratio',`${frame.naturalWidth} / ${frame.naturalHeight}`));
  const rows = [...$('hunter-feed').children].slice(0,9);
  let sites = [...left.querySelectorAll('.hunter-site')];
  // live is null until probed, then true when the server exposes the sourcing API.
  let live = null, source = null, runId = null, maxCandidates = 10, lostTimer = null, shownUrl = '';
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
  // A rising major triad, softer than the capture blip, marks the end of a run.
  function playDone() {
    if(!soundOn || !audio)return;
    const now = audio.currentTime;
    [[784,0],[988,.09],[1175,.18],[1568,.27]].forEach(([frequency,delay]) => {
      const osc = audio.createOscillator(), gain = audio.createGain(), start = now + delay;
      osc.type = 'triangle';osc.frequency.value = frequency;
      gain.gain.setValueAtTime(.001,start);gain.gain.exponentialRampToValueAtTime(.07,start + .01);gain.gain.exponentialRampToValueAtTime(.001,start + .5);
      osc.connect(gain);gain.connect(audio.destination);
      osc.onended = () => gain.disconnect();
      osc.start(start);osc.stop(start + .52);
    });
  }
  // Lock-on rings over the browser, a green wave down the cards, and a glow on the progress bar.
  function celebrate(count) {
    playDone();
    const done = piece('div','hunter-done');done.setAttribute('aria-hidden','true');
    const tally = piece('span','');
    tally.append(piece('em','',String(count).padStart(2,'0')),` CANDIDATE${count === 1 ? '' : 'S'} ACQUIRED`);
    // A solid card keeps the stamp readable over a busy page; the rings expand behind it.
    const stamp = piece('div','hunter-done-card');
    stamp.append(piece('small','','// SOURCING RUN'),piece('b','','MISSION COMPLETE'),tally);
    done.append(piece('i',''),piece('i',''),stamp);
    $('hunter-screen').querySelector('.hunter-done')?.remove();
    $('hunter-screen').append(done);
    timers.push(setTimeout(() => done.classList.add('is-out'),reduced ? 1800 : 2600));
    timers.push(setTimeout(() => done.remove(),reduced ? 1800 : 3100));
    $('hunter-track').classList.remove('is-done');void $('hunter-track').offsetWidth;$('hunter-track').classList.add('is-done');
    // Cards cheer in their on-screen order, which CSS order may have changed.
    [...$('hunter-list').querySelectorAll('.hunter-card:not([hidden])')]
      .sort((a,b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top)
      .forEach((card,index) => {
        card.classList.remove('is-cheer');void card.offsetWidth;
        card.style.setProperty('--cheer',index * 70 + 'ms');card.classList.add('is-cheer');
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
    const fit = piece('p',`hunter-fit${person.fit === '符合' ? ' is-strong' : person.fit === '部分符合' ? '' : ' is-unknown'}`,person.fit);
    const button = piece('button','hunter-detail','查看評估');button.type = 'button';button.setAttribute('aria-expanded','false');
    const more = piece('div','hunter-more');more.hidden = true;
    more.append(piece('p','',`判斷理由：${person.reason || '未提供'}`));
    if(person.evidence?.length) {
      const links = piece('p','hunter-links','依據：');
      person.evidence.forEach(({label,url}) => {
        // Only http(s) links from the backend become anchors.
        if(!/^https?:\/\//.test(url))return;
        const link = piece('a','',label);link.href = url;link.target = '_blank';link.rel = 'noopener noreferrer';
        link.addEventListener('click',event => event.stopPropagation());
        links.append(link,' ');
      });
      more.append(links);
    } else more.append(piece('p','','依據：公開個人頁（展示資料）'));
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
    // Live frames get a 0.15s scanline wipe; the mock keeps its longer glitch.
    const effect = live ? 'wipe' : 'glitch';
    screen.classList.remove('glitch','wipe');void screen.offsetWidth;screen.classList.add(effect);
    timers.push(setTimeout(() => screen.classList.remove(effect),live ? 200 : 520));
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
      celebrate(captured.length + (step.people?.length ?? 0));
    }
  }
  function stopLive() {
    source?.close();source = null;
    if(runId)fetch(`/api/sourcing/runs/${runId}`,{method:'DELETE'}).catch(() => {});
    runId = null;
  }
  function finishRun(text,tone) {
    source?.close();source = null;runId = null;
    // A failed run keeps the progress it reached and turns the bar red instead of claiming 100%.
    if(tone === 'err')$('hunter-track').classList.add('is-failed');else setProgress(100);
    $('hunter-state').textContent = '目前狀態：' + text;addLog(text,tone);
    $('hunter-screen').classList.remove('running');left.classList.remove('is-hunting');$('hunter-start').disabled = false;
    sweepEnd = performance.now();
  }
  // geometry is in frame pixels; the frame is drawn with object-fit: contain, so map through its letterbox.
  function showGeometry(geometry,kind) {
    if(!geometry || frame.hidden)return;
    const screen = $('hunter-screen'), fw = geometry.frame?.w || 1280, fh = geometry.frame?.h || 800;
    // A box measured below the fold would land outside the picture, so it is dropped rather than clipped.
    const inside = ({x,y,w = 0,h = 0}) => x + w > 0 && y + h > 0 && x < fw && y < fh;
    if(geometry.box && !inside(geometry.box))geometry = {...geometry,box:null};
    if(geometry.click && !inside(geometry.click))geometry = {...geometry,click:null};
    const scale = Math.min(screen.clientWidth / fw,screen.clientHeight / fh);
    const left = (screen.clientWidth - fw * scale) / 2, top = (screen.clientHeight - fh * scale) / 2;
    const at = (x,y) => [left + x * scale,top + y * scale];
    if(geometry.box) {
      const {x,y,w,h} = geometry.box, [bx,by] = at(x,y), box = piece('i',`hunter-box is-${kind}`);
      Object.assign(box.style,{left:bx + 'px',top:by + 'px',width:w * scale + 'px',height:h * scale + 'px'});
      screen.append(box);timers.push(setTimeout(() => box.remove(),1400));
    }
    if(geometry.click) {
      const [cx,cy] = at(geometry.click.x,geometry.click.y), cursor = $('hunter-cursor');
      cursor.classList.add('is-live');cursor.style.left = cx - 6 + 'px';cursor.style.top = cy - 6 + 'px';
      if(reduced)return;
      // The beacon lands once the cursor has glided over, then fades within the second the docs suggest.
      timers.push(setTimeout(() => {
        const beacon = piece('i','hunter-beacon');beacon.style.left = cx + 'px';beacon.style.top = cy + 'px';
        screen.append(beacon);timers.push(setTimeout(() => beacon.remove(),900));
      },reduced ? 0 : 450));
    }
  }
  const siteLabel = id => sites.find(site => site.dataset.site === id)?.textContent || id || '';
  // Maps one PR #24 event onto the same panels the mock drives.
  function handleLive(type,event) {
    const where = event.site ? siteLabel(event.site) + '：' : '';
    switch(type) {
      case 'frame':frame.src = event.data;frame.hidden = false;break;
      case 'plan': {
        const plan = event.plan;
        addLog(`[PLAN] 技能 ${plan.skills.join('、') || '未指定'}${plan.location ? '・地點 ' + plan.location : ''}・網站 ${event.sites.map(site => site.name).join('、')}`);
        $('hunter-state').textContent = '目前狀態：開始搜尋';setProgress(5);
        break;
      }
      case 'decision':addLog(`[${event.by === 'gpt-6-luna' ? 'LUNA' : 'RULE'}] ${where}${event.detail}`);break;
      case 'step':
        addLog(`[STEP] ${where}${event.detail}`,event.action === 'fallback' || event.action === 'jev_refused' ? 'warn' : undefined);
        // Geometry is measured before the action, but the step arrives after it. When the action changed the
        // page, the current frame already shows the next page and the marker would point at the wrong thing.
        const sameShot = !event.url || event.url === shownUrl;
        if(event.url){switchPage(event.url);shownUrl = event.url;}
        markSite(event.site);$('hunter-state').textContent = '目前狀態：' + where + event.detail;
        if(event.screenshot && frame.hidden){frame.src = event.screenshot;frame.hidden = false;}
        if(sameShot)showGeometry(event.geometry,'click');
        break;
      case 'candidate': {
        const person = event.candidate;
        // The log line and the name's box on the page light up together.
        addLog(`[FOUND] ${where}${person.name}（${person.fit}）`,event.geometry ? 'ok is-linked' : 'ok');
        showGeometry(event.geometry,'found');
        addPerson({name:person.name,summary:person.headline || person.summary || '',fit:person.fit,reason:person.fit_reason,evidence:person.evidence});
        playCapture();setProgress(Math.min(95,5 + Math.round(captured.length / maxCandidates * 90)));
        break;
      }
      case 'candidate_skipped':addLog(`[SKIP] ${where}${event.name}：${event.reason || '不符合需求'}`,'warn');break;
      case 'site_skipped':addLog(`[SKIP] ${where}${event.reason}`,'warn');markSite(event.site,true);break;
      case 'site_error':addLog(`[ERROR] ${where}${event.reason}`,'err');markSite(event.site,true);break;
      case 'notice':addLog(`[NOTICE] ${event.message}`,'warn');break;
      case 'rejected':finishRun(`已拒絕：${event.reason}`,'warn');break;
      case 'no_public_work':finishRun(event.advice || '這類職缺網路上少有公開作品，建議改用其他管道。','warn');break;
      case 'error':finishRun(`發生錯誤：${event.reason}`,'err');break;
      case 'done': {
        // Without a key no model runs, so a zero-cost line would only add noise.
        const usage = event.usage?.total_tokens ? `・約 ${event.usage.total_tokens.toLocaleString()} token、US$${event.usage.total_cost_usd.toFixed(4)}` : '';
        finishRun(event.cancelled ? `已停止，停止前找到 ${event.count} 位` : `任務完成，找到 ${event.count} 位${usage}`,event.cancelled ? undefined : 'ok');
        if(!event.cancelled && event.count)celebrate(event.count);
        break;
      }
    }
  }
  const LIVE_EVENTS = ['plan','decision','step','frame','candidate','candidate_skipped','site_skipped','site_error','notice','rejected','no_public_work','error','done'];
  async function startLive(chosen) {
    const current = run;
    // Clamped to the backend's 1-20 range so an odd entry never turns into a 422.
    maxCandidates = Math.min(20,Math.max(1,Math.round(Number($('hunter-max').value)) || 10));$('hunter-max').value = maxCandidates;
    const body = {query:$('hunter-job').value.trim(),max_candidates:maxCandidates};
    if(chosen.size)body.sites = [...chosen];
    let res, data = {};
    try {
      res = await fetch('/api/sourcing/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      data = await res.json().catch(() => ({}));
    } catch { return current === run && finishRun('連不上後端','err'); }
    if(current !== run)return;
    if(!res.ok)return finishRun(`後端回 HTTP ${res.status}：${typeof data.detail === 'string' ? data.detail : '請確認職缺描述（2～300 字）'}`,'err');
    runId = data.run_id;
    // EventSource reconnects with Last-Event-ID on its own, so a dropped connection does not lose events.
    source = new EventSource(data.events_url);
    LIVE_EVENTS.forEach(type => source.addEventListener(type,message => {
      // The backend's own 'error' event shares its name with EventSource's connection error, which has no data.
      if(message.data === undefined)return;
      clearTimeout(lostTimer);lostTimer = null;
      if(current === run)handleLive(type,JSON.parse(message.data));
    }));
    source.addEventListener('end',() => {source?.close();source = null;runId = null;});
    // EventSource retries forever while the server is down, and gives up for good on a 404 after a restart.
    const lost = () => {
      lostTimer = null;
      if(current !== run || !source)return;
      stopLive();finishRun('與後端的連線中斷，任務已停止','err');
    };
    source.addEventListener('open',() => {clearTimeout(lostTimer);lostTimer = null;});
    source.addEventListener('error',() => {
      if(source?.readyState === EventSource.CLOSED)lost();
      else lostTimer ??= setTimeout(lost,12000);
    });
  }
  async function probeLive() {
    if(live !== null)return;
    try {
      const res = await fetch('/api/sourcing/sites');
      if(!res.ok)throw 0;
      // Personal sites are only read from profile links, never searched, so they get no chip.
      const list = (await res.json()).sites.filter(site => !['personal','gitlab','behance'].includes(site.id));
      live = true;
      // Nothing ticked means the backend picks sites by job category.
      const chips = list.map(site => {
        const chip = piece('label',`hunter-site${site.available ? '' : ' is-off'}`);chip.dataset.site = site.id;
        const box = document.createElement('input');box.type = 'checkbox';box.disabled = !site.available;
        if(!site.available)chip.title = site.unavailable_reason || '不可用';
        chip.append(box,document.createElement('i'),site.name);
        return chip;
      });
      left.querySelector('.hunter-sites').replaceChildren(...chips);
      sites = chips;
      left.querySelector('.hunter-mode').textContent = '即時模式・公開作品網站';
      $('hunter-max-field').hidden = false;
      $('hunter-scope').hidden = false;
      right.querySelector('.hunter-note').textContent = '公開作品網站沒有住址，候選人不標在地圖上。';
      right.querySelector('.hunter-sim').textContent = 'Computer Use 即時畫面';
      $('hunter-job').value = '找會 Python 的軟體工程師，在台中';$('hunter-tag').textContent = $('hunter-job').value;
    } catch { live = false; }
  }
  function reset() {
    clearTimeout(lostTimer);lostTimer = null;shownUrl = '';stopLive();setBig(false);$('hunter-cursor').classList.remove('is-live');$('hunter-track').classList.remove('is-done','is-failed');$('hunter-screen').querySelector('.hunter-done')?.remove();frame.hidden = true;frame.removeAttribute('src');
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
    reset();unlockAudio();setBig(true);$('hunter-start').disabled = true;$('hunter-start').textContent = '重新開始';
    $('hunter-state').textContent = '目前狀態：任務啟動中';$('hunter-screen').classList.add('running');left.classList.add('is-hunting');
    const current = run;
    // The panels still run without the map layer if the boundary file fails to load.
    try { await loadCentres(); } catch {}
    await probeLive();
    if(!active || current !== run)return;
    if(!live)fitCandidates();
    const map = window.streetMap.getMap(), origin = window.streetMap.getLocation()?.coordinates;
    if(map && centres) {
      ensureLayers(map);flowLinks(map);
      if(origin && !reduced)runSweep(map,origin);
    }
    const chosen = new Set(sites.filter(site => site.querySelector('input').checked).map(site => site.dataset.site));
    live ? startLive(chosen) : connectStream(chosen);
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
    probeLive();
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
  $('hunter-zoom').addEventListener('click',() => setBig(!big));
  // Closing the tab mid-run would otherwise keep a Chrome and one of the two run slots busy until it finishes.
  addEventListener('pagehide',() => {if(runId)fetch(`/api/sourcing/runs/${runId}`,{method:'DELETE',keepalive:true}).catch(() => {});});
  roomy.addEventListener('change',() => {if(!roomy.matches)setBig(false);});
  $('hunter-job').addEventListener('input',event => {$('hunter-tag').textContent = event.target.value.trim() || '未填職缺';});
  $('hunter-sound').addEventListener('click',() => {
    soundOn = !soundOn;syncSound();
    try { localStorage.setItem('radar-sound',soundOn ? 'on' : 'off'); } catch {}
    unlockAudio();playCapture();
  });
  syncSound();reset();
  window.headhunter = {toggle(){active ? deactivate() : activate();},deactivate};
})();
