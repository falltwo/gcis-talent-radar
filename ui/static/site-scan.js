/* Step 3: after the radar burst, rank Taichung's 29 districts from GCIS and factory data and light them up on the map. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  // ponytail: keyword rules stand in for the AI parser; first match wins. Swap for the real parser when it exists.
  const INDUSTRY_WORDS = [['機械','機械設備業'],['金屬','金屬製品業'],['加工','金屬製品業'],['塑膠','塑膠製品業'],['半導體','電子零組件業'],['電子','電子零組件業'],['光學','電腦電子產品及光學製品業'],['食品','食品及飼品業'],['飲料','飲料及菸草業'],['汽車','汽車及其零件業'],['自行車','其他運輸工具及其零件業'],['家具','家具業'],['紡織','紡織業'],['成衣','成衣及服飾品業'],['化學','其他化學製品業'],['橡膠','橡膠製品業'],['印刷','印刷及資料儲存媒體複製業']];
  const CRITERIA = [
    {id:'vitality', label:'市場活力', hint:'全產業公司近一年新設減解散（名冊沒有行業欄）', unit:'家', better:1, words:['活力','成長','新創']},
    {id:'stability', label:'經營穩定', hint:'解散家數 ÷ 新設家數，越低越好', unit:'', better:-1, words:['穩定','風險']},
    {id:'cluster', label:'同業群聚', hint:'同業工廠家數', unit:'家', better:1, words:['供應鏈','上下游','群聚','聚落']},
    {id:'competition', label:'避開競爭', hint:'每百家工廠的製造類職缺，越少越好（職缺與工廠年份不同）', unit:'筆', better:-1, words:['競爭','搶人']},
  ];
  // ponytail: fixed gate; districts with few factories are not realistic sites and would win "low competition" by default.
  const MIN_FACTORIES = 100, MIN_SETUPS = 30;
  const PREFERENCE = {'上下游群聚優先':'cluster','避開激烈競爭':'competition','靠近交通樞紐':null};
  const NO_DATA_WORDS = ['交流道','國道','交通','港口','機場','高鐵'];
  let map, geo, activity, stats, talent, intent, industry, checked = {}, boosted = {}, ranking = [], frame = 0, started = false;
  let revealed = false, located = false;

  const stage = $('city-stage');
  const left = document.createElement('aside');
  left.className = 'scan-side scan-left';left.setAttribute('aria-label','選址條件');left.inert = true;
  left.innerHTML = `
    <div class="scan-pane scan-report-only"><h3>1. 人才供給與職缺需求</h3><div class="scan-body"><div id="report-supply"></div><p class="scan-note" id="report-supply-note"></p></div></div>
    <div class="scan-pane scan-report-only"><h3>2. 附近的關鍵學校</h3><div class="scan-body"><div id="report-schools"></div></div></div>
    <div class="scan-pane scan-rank-only"><h3>從需求擷取的條件</h3><div class="scan-body"><div class="scan-tags" id="scan-tags"></div><p class="scan-note" id="scan-intent-note"></p></div></div>
    <div class="scan-pane scan-rank-only"><h3>商工行政環境篩選</h3><div class="scan-body"><div id="scan-criteria"></div><p class="scan-note" id="scan-gap"></p></div></div>
    <button type="button" class="scan-close" id="scan-close">結束掃描，回到街區地圖</button>`;
  const right = document.createElement('aside');
  right.className = 'scan-side scan-right';right.setAttribute('aria-label','推薦建廠熱區');right.inert = true;
  right.innerHTML = `
    <div class="scan-pane scan-report-only"><h3>3. 職缺開出的月薪</h3><div class="scan-body"><div id="report-salary"></div><p class="scan-note">雇主在就業通刊登的薪資，不是求職者的期望薪資。</p></div></div>
    <div class="scan-pane scan-report-only"><h3>4. 招募建議 <span>系統依上面數字產生，非 AI</span></h3><div class="scan-body"><ul class="report-advice" id="report-advice"></ul>
      <div class="report-actions"><button type="button" id="report-back">← 回到排名</button></div>
      <p class="scan-note" id="report-source"></p></div></div>
    <div class="scan-pane scan-rank-only"><h3>商工資料推薦熱區 <span>Top 12</span></h3>
      <div class="scan-body"><ol class="scan-grid" id="scan-podium"></ol>
      <button type="button" class="scan-compare" id="scan-compare">比較前三區的人才</button>
      <details class="scan-check"><summary><b>換權重會換答案嗎？</b><span id="scan-check-summary"></span></summary><ul id="scan-check-list"></ul></details>
      <ol class="scan-grid scan-rest" id="scan-grid" start="4"></ol>
      <p class="scan-note" id="scan-source"></p></div></div>`;
  stage.append(left, right);
  const status = document.createElement('p');
  status.className = 'scan-status';status.id = 'scan-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  stage.append(status);

  function parseIntent(raw) {
    const text = raw?.text || '', preference = raw?.preference || '';
    industry = INDUSTRY_WORDS.find(([word]) => text.includes(word))?.[1] || null;
    checked = Object.fromEntries(CRITERIA.map(c => [c.id, true]));
    boosted = Object.fromEntries(CRITERIA.map(c => [c.id, c.words.some(word => text.includes(word))]));
    if (PREFERENCE[preference]) boosted[PREFERENCE[preference]] = true;
    const tags = [];
    tags.push(industry ? ['產業', industry] : ['產業', '未判斷，看全部製造業']);
    if (preference) tags.push(['偏好', preference]);
    CRITERIA.filter(c => boosted[c.id]).forEach(c => tags.push(['加重', c.label]));
    const missing = NO_DATA_WORDS.filter(word => text.includes(word)).concat(preference === '靠近交通樞紐' ? ['交通樞紐'] : []);
    $('scan-tags').replaceChildren(...tags.map(([kind, value]) => {
      const tag = document.createElement('span');tag.className = 'scan-tag';
      tag.innerHTML = '<small></small><b></b>';tag.firstChild.textContent = kind;tag.lastChild.textContent = value;
      return tag;
    }));
    $('scan-intent-note').textContent = text ? `「${text}」・目前用關鍵字擷取，尚未接 AI 解析` : '沒有輸入文字，只依偏好按鈕設定。';
    $('scan-gap').textContent = missing.length ? `沒有${[...new Set(missing)].join('、')}的資料，這次未納入排名。` : '';
  }

  function factoryTotal(name) {
    const known = Object.values(stats.factories.districts[name] || {}).filter(count => count !== null);
    return known.reduce((sum, count) => sum + count, 0);
  }
  function value(name, id) {
    const row = activity.districts[name] || {setup:0, dissolved:0};
    if (id === 'vitality') return row.setup - row.dissolved;
    if (id === 'stability') return row.setup >= MIN_SETUPS ? row.dissolved / row.setup : null;
    if (id === 'cluster') {
      const factories = stats.factories.districts[name];
      if (!factories) return null;
      if (industry) return factories[industry] ?? null;
      const known = Object.values(factories).filter(count => count !== null);
      return known.length ? known.reduce((sum, count) => sum + count, 0) : null;
    }
    if (stats.jobs.capped.includes(name)) return null;
    const postings = stats.jobs.metrics.manufacturing_postings[name];
    return postings === undefined ? null : postings / factoryTotal(name) * 100;
  }
  // Each criterion is rescaled to 0–1 across the candidate districts; a missing value drops that criterion for that district only.
  let candidates = [];
  function rank() {
    const names = candidates = geo.features.map(feature => feature.properties.TOWNNAME).filter(name => factoryTotal(name) >= MIN_FACTORIES);
    const raw = Object.fromEntries(CRITERIA.map(c => [c.id, Object.fromEntries(names.map(name => [name, value(name, c.id)]))]));
    const scaled = {};
    for (const c of CRITERIA) {
      const known = Object.values(raw[c.id]).filter(v => v !== null), low = Math.min(...known), high = Math.max(...known);
      scaled[c.id] = Object.fromEntries(names.map(name => {
        const v = raw[c.id][name];
        if (v === null || high === low) return [name, null];
        const share = (v - low) / (high - low);
        return [name, c.better > 0 ? share : 1 - share];
      }));
    }
    lastScaled = scaled;lastRaw = raw;
    ranking = scoreWith(checked, boosted);
  }
  let lastScaled, lastRaw;
  function scoreWith(use, heavy) {
    return candidates.map(name => {
      const scaled = lastScaled, raw = lastRaw;
      let sum = 0, weight = 0, best = null;
      for (const c of CRITERIA) {
        if (!use[c.id] || scaled[c.id][name] === null) continue;
        const w = heavy[c.id] ? 2 : 1;
        sum += w * scaled[c.id][name];weight += w;
        if (!best || scaled[c.id][name] > scaled[best.id][name]) best = c;
      }
      return {name, score: weight ? sum / weight : null, best, raw: Object.fromEntries(CRITERIA.map(c => [c.id, raw[c.id][name]]))};
    }).sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  }
  // Sensitivity check: rerun with no extra weight and with each checked criterion doubled on its own.
  function sensitivity() {
    const used = CRITERIA.filter(c => checked[c.id]);
    const none = Object.fromEntries(CRITERIA.map(c => [c.id, false]));
    const runs = [{label:'不加重任何一項', heavy:none}, ...used.map(c => ({label:`加重${c.label}`, heavy:{...none, [c.id]:true}}))];
    return runs.map(run => {
      const list = scoreWith(checked, run.heavy);
      return {...run, first:list[0]?.name, top3:list.slice(0, 3).map(item => item.name)};
    });
  }
  function describe(c, v) {
    if (v === null || v === undefined) return '無資料';
    if (c.id === 'stability') return `每新設 100 家解散 ${Math.round(v * 100)} 家`;
    if (c.id === 'vitality') return `${v >= 0 ? '+' : ''}${v.toLocaleString()} 家`;
    if (c.id === 'competition') return `每百家工廠 ${Math.round(v)} 筆`;
    return `${v.toLocaleString()} ${c.unit}`;
  }

  function renderCriteria() {
    $('scan-criteria').replaceChildren(...CRITERIA.map(c => {
      const row = document.createElement('label');row.className = 'scan-criterion';
      row.innerHTML = '<input type="checkbox"><span><b></b><small></small></span><em></em>';
      const box = row.querySelector('input');box.checked = checked[c.id];
      row.querySelector('b').textContent = c.id === 'cluster' && industry ? `${c.label}（${industry}）` : c.label;
      row.querySelector('small').textContent = c.hint;
      row.querySelector('em').textContent = boosted[c.id] ? '權重 ×2' : '';
      box.addEventListener('change', () => {
        checked[c.id] = box.checked;
        if (!CRITERIA.some(item => checked[item.id])) {checked[c.id] = box.checked = true;return;}
        rank();paintScores(true);renderCards();
      });
      return row;
    }));
  }
  function renderCards() {
    const top = ranking.slice(0, 12);
    const cards = top.map((item, index) => {
      const card = document.createElement('li');card.className = 'scan-card' + (index === 0 ? ' is-top' : '') + (index < 3 ? ' is-podium' : '');
      card.style.setProperty('--delay', (reduced ? 0 : index * 60) + 'ms');
      card.innerHTML = '<button type="button"><span class="scan-rank"></span><strong></strong><span class="scan-score"></span><small></small></button>';
      card.querySelector('.scan-rank').textContent = '#' + (index + 1);
      card.querySelector('strong').textContent = item.name;
      card.querySelector('.scan-score').textContent = item.score === null ? '—' : Math.round(item.score * 100);
      card.querySelector('small').textContent = index < 3
        ? CRITERIA.filter(c => checked[c.id]).map(c => `${c.label}：${describe(c, item.raw[c.id])}`).join('\n')
        : item.best ? `${item.best.label} ${describe(item.best, item.raw[item.best.id])}` : '';
      card.querySelector('button').setAttribute('aria-label', `第 ${index + 1} 名 ${item.name}，相對分數 ${card.querySelector('.scan-score').textContent}`);
      card.querySelector('button').addEventListener('click', () => focusDistrict(item.name));
      return card;
    });
    $('scan-podium').replaceChildren(...cards.slice(0, 3));
    $('scan-grid').replaceChildren(...cards.slice(3));
    const three = top.slice(0, 3).map(item => item.name);
    $('scan-compare').textContent = `比較${three.join('、')}的人才 →`;
    const runs = sensitivity(), firsts = [...new Set(runs.map(run => run.first))];
    const sameTop3 = runs.every(run => run.top3.slice().sort().join() === three.slice().sort().join());
    $('scan-check-summary').textContent = firsts.length === 1
      ? `不管加重哪一項，第一名都是${firsts[0]}。${sameTop3 ? '前三名也都一樣。' : '前三名會有變動。'}`
      : `第一名會隨權重改變：${runs.filter(run => run.first !== ranking[0]?.name).map(run => `${run.label} → ${run.first}`).join('；')}。`;
    $('scan-check-list').replaceChildren(...runs.map(run => {
      const row = document.createElement('li');
      row.textContent = `${run.label}：${run.top3.join('、')}`;
      return row;
    }));
    $('scan-source').textContent = `分數 0–100 是 ${candidates.length} 個候選區互相比較的相對值，不是預測或匹配率；製造業工廠不到 ${MIN_FACTORIES} 家的 ${geo.features.length - candidates.length} 區不列入。資料：商工登記 ${activity.window.join(' 至 ')}${activity.missing_months.length ? `（缺 ${activity.missing_months.join('、')}）` : ''}、工廠校正 ${stats.factories.year} 年、就業通職缺 ${stats.jobs.snapshot_date}。`;
  }

  function bounds(feature) {
    let west = 180, south = 90, east = -180, north = -90;
    const walk = coords => typeof coords[0] === 'number'
      ? (west = Math.min(west, coords[0]), east = Math.max(east, coords[0]), south = Math.min(south, coords[1]), north = Math.max(north, coords[1]))
      : coords.forEach(walk);
    // The city overview frames the candidate districts; the mountain districts would shrink everything else.
    walk(feature ? feature.geometry.coordinates : geo.features.filter(f => candidates.includes(f.properties.TOWNNAME)).map(f => f.geometry.coordinates));
    return [[west, south], [east, north]];
  }
  function padding() {
    const narrow = innerWidth <= 960;
    return narrow ? {top:70, bottom:Math.round(stage.clientHeight * .45), left:16, right:16} : {top:80, bottom:40, left:left.offsetWidth + 36, right:right.offsetWidth + 36};
  }
  function focusDistrict(name) {
    const feature = geo.features.find(f => f.properties.TOWNNAME === name);
    if (!feature) return;
    map.fitBounds(bounds(feature), {padding:padding(), maxZoom:12.5, pitch:0, bearing:0, duration:reduced ? 0 : 1100});
    status.textContent = `已移到${name}`;
  }
  // Scores feed a feature-state colour; "lit" ramps each district from dark to its own brightness.
  function paintScores(instant) {
    cancelAnimationFrame(frame);
    const top = ranking[0]?.name;
    map.setFilter('scan-top', ['==', ['get','TOWNNAME'], top || '']);
    map.setFilter('scan-top-glow', ['==', ['get','TOWNNAME'], top || '']);
    geo.features.forEach(f => map.setFeatureState({source:'scan', id:f.properties.TOWNNAME}, {score:0, top:false, out:!candidates.includes(f.properties.TOWNNAME)}));
    ranking.forEach(item => map.setFeatureState({source:'scan', id:item.name}, {score:item.score ?? 0, top:item.name === top}));
    if (instant || reduced) {
      ranking.forEach(item => map.setFeatureState({source:'scan', id:item.name}, {lit:1}));
      map.setPaintProperty('scan-top', 'line-opacity', 1);
      return;
    }
    // West-to-east sweep, so the light reads as one scan crossing the city.
    const order = geo.features.map(f => ({name:f.properties.TOWNNAME, x:bounds(f)[0][0]})).sort((a, b) => a.x - b.x);
    const begin = performance.now(), stagger = 70, fade = 450, total = order.length * stagger + fade;
    map.setPaintProperty('scan-top', 'line-opacity', 0);
    const step = now => {
      const t = now - begin;
      order.forEach(({name}, index) => map.setFeatureState({source:'scan', id:name}, {lit:Math.max(0, Math.min(1, (t - index * stagger) / fade))}));
      if (t < total) frame = requestAnimationFrame(step);
      else {map.setPaintProperty('scan-top', 'line-opacity', 1);status.textContent = `掃描完成：第一名${top}`;}
    };
    frame = requestAnimationFrame(step);
  }
  function addLayers() {
    if (map.getSource('scan')) return;
    map.addSource('scan', {type:'geojson', data:geo, promoteId:'TOWNNAME'});
    const lit = ['coalesce', ['feature-state','lit'], 0], score = ['coalesce', ['feature-state','score'], 0];
    map.addLayer({id:'scan-fill', type:'fill', source:'scan', paint:{
      'fill-color':['case', ['boolean', ['feature-state','pick'], false], '#fb923c', ['all', ['boolean', ['feature-state','top'], false], ['>=', lit, 1]], '#f97316', ['boolean', ['feature-state','out'], false], '#9aa3ae',
        ['interpolate', ['linear'], ['*', score, lit], 0, '#1e2b40', .5, '#3f7fd0', 1, '#9fd0ff']],
      'fill-opacity':['*', lit, ['case', ['boolean', ['feature-state','dim'], false], .12, ['boolean', ['feature-state','out'], false], .25, .66]]}});
    map.addLayer({id:'scan-edge', type:'line', source:'scan', paint:{'line-color':'#ffffff', 'line-width':.8, 'line-opacity':['*', lit, .7]}});
    map.addLayer({id:'scan-top-glow', type:'line', source:'scan', filter:['==', ['get','TOWNNAME'], ''], paint:{'line-color':'#fb923c', 'line-width':9, 'line-blur':6, 'line-opacity':.55}});
    map.addLayer({id:'scan-top', type:'line', source:'scan', filter:['==', ['get','TOWNNAME'], ''], paint:{'line-color':'#ea580c', 'line-width':2.4, 'line-opacity':0, 'line-opacity-transition':{duration:400}}});
  }
  function setVisible(on) {
    for (const id of ['scan-fill','scan-edge','scan-top-glow','scan-top']) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
  }

  // Three-district report: what the open data can say about hiring in each place, nothing estimated.
  function centre(name) {
    const [[w, s], [e, n]] = bounds(geo.features.find(f => f.properties.TOWNNAME === name));
    return [(w + e) / 2, (s + n) / 2];
  }
  function bar(label, value, max, unit, tone) {
    const row = document.createElement('div');row.className = 'report-bar ' + tone;
    row.innerHTML = '<span></span><i><b></b></i><em></em>';
    row.firstChild.textContent = label;
    row.querySelector('b').style.width = (max ? Math.max(2, value / max * 100) : 0) + '%';
    row.querySelector('em').textContent = value.toLocaleString() + ' ' + unit;
    return row;
  }
  const short = name => name.replace('學校財團法人修平', '');
  function section(name) {
    const box = document.createElement('section');box.className = 'report-district';
    const head = document.createElement('h4');head.textContent = name;box.append(head);
    return [box, head];
  }
  function renderReport(three) {
    const rows = three.map(name => ({name, ...talent.districts[name]}));
    rows.forEach(row => {row.ratio = row.graduates_nearby ? row.openings / row.graduates_nearby : null;});
    const order = rows.filter(row => row.ratio !== null).sort((a, b) => a.ratio - b.ratio);
    const level = row => row.ratio === null ? '附近沒有相關科系' : order.length < 2 ? '' : row === order[0] ? '三區中較容易' : row === order[order.length - 1] ? '三區中較難' : '居中';
    const maxGrad = Math.max(...rows.map(r => r.graduates_nearby)), maxOpen = Math.max(...rows.map(r => r.openings));
    $('report-supply').replaceChildren(...rows.map(row => {
      const [box, head] = section(row.name);
      const tag = document.createElement('span');tag.className = 'report-level' + (row === order[0] ? ' is-easy' : '');tag.textContent = level(row);head.append(tag);
      const ratio = document.createElement('p');ratio.className = 'report-ratio';
      ratio.textContent = row.ratio === null ? `${talent.radius_km} 公里內沒有大專相關科系` : `每位畢業生對應 ${row.ratio.toFixed(2)} 個職缺需求`;
      box.append(bar('相關科系畢業生', row.graduates_nearby, maxGrad, '人', 'is-supply'), bar('製造類職缺需求', row.openings, maxOpen, '人', 'is-demand'), ratio);
      return box;
    }));
    $('report-supply-note').textContent = `畢業生：區中心 ${talent.radius_km} 公里內大專校院機械、電機等相關科系 ${talent.academic_year} 學年畢業生，不含高職。職缺：就業通 ${talent.jobs_snapshot} 快照的技術、製造、工程類需求人數。沒有各區求職者人數的資料，所以這不是求職求才比。`;
    $('report-schools').replaceChildren(...rows.map(row => {
      const [box] = section(row.name);
      const list = document.createElement('ul');list.className = 'report-school-list';
      const top = row.schools.slice().sort((a, b) => b.graduates - a.graduates).slice(0, 2);
      if (!top.length) {const li = document.createElement('li');li.textContent = `${talent.radius_km} 公里內沒有大專校院相關科系`;list.append(li);}
      top.forEach(school => {
        const li = document.createElement('li');li.innerHTML = '<b></b><small></small>';
        li.firstChild.textContent = short(school.name);
        li.lastChild.textContent = `${school.district}・距 ${school.km} 公里・相關科系 ${school.graduates} 人・${school.top_departments.slice(0, 2).join('、')}`;
        list.append(li);
      });
      box.append(list);return box;
    }));
    const maxPay = Math.max(...rows.map(r => r.salary_ceiling_median || r.salary_floor_median || 0));
    $('report-salary').replaceChildren(...rows.map(row => {
      const [box] = section(row.name);
      if (row.salary_floor_median) box.append(bar(`起薪中位數（${row.salary_samples} 筆）`, row.salary_floor_median, maxPay, '元', 'is-pay'));
      if (row.salary_ceiling_median) box.append(bar(`上限中位數（${row.salary_ceiling_samples} 筆）`, row.salary_ceiling_median, maxPay, '元', 'is-pay-high'));
      if (!row.salary_floor_median) {const p = document.createElement('p');p.className = 'report-ratio';p.textContent = '沒有月薪刊登';box.append(p);}
      return box;
    }));
    const advice = [];
    if (order.length) advice.push(`對照相關科系畢業生和職缺需求，${order[0].name}每位畢業生對應的職缺需求最少（${order[0].ratio.toFixed(2)}），新鮮人的招募壓力在三區中最低。`);
    rows.filter(row => row.ratio === null).forEach(row => advice.push(`${row.name} ${talent.radius_km} 公里內沒有大專相關科系，新鮮人要從外區通勤，比較適合用刊登召募找有經驗的人。`));
    three.forEach((a, i) => three.slice(i + 1).forEach(b => {
      const both = talent.districts[a].schools.filter(x => talent.districts[b].schools.some(y => y.name === x.name)).map(x => short(x.name));
      if (both.length) advice.push(`${a}和${b}附近有相同的學校（${both.slice(0, 2).join('、')}），選其中一區，另一區的學校也在通勤範圍內。`);
    }));
    const floors = rows.map(r => r.salary_floor_median).filter(Boolean);
    if (floors.length > 1) advice.push(new Set(floors).size === 1
      ? `三區開出的起薪中位數都是 ${floors[0].toLocaleString()} 元，起薪不是區分因素。`
      : `起薪中位數最高的是${rows.find(r => r.salary_floor_median === Math.max(...floors)).name}（${Math.max(...floors).toLocaleString()} 元），在那裡招人起薪要開得比較高。`);
    advice.push('這只看新鮮人供給和公開職缺；沒有求職者人數、期望薪資和地價資料，最後仍要實地評估。');
    $('report-advice').replaceChildren(...advice.map(text => {const li = document.createElement('li');li.textContent = text;return li;}));
    $('report-source').textContent = `資料：${talent.sources.graduates}；${talent.sources.campuses}；${talent.sources.jobs}。`;
  }
  let pulse = 0;
  function showReportMap(three) {
    const points = three.map(centre);
    const data = {type:'FeatureCollection', features:[
      ...points.flatMap((a, i) => points.slice(i + 1).map(b => ({type:'Feature', properties:{}, geometry:{type:'LineString', coordinates:[a, b]}}))),
      ...points.map((point, i) => ({type:'Feature', properties:{name:three[i]}, geometry:{type:'Point', coordinates:point}})),
    ]};
    if (map.getSource('report')) map.getSource('report').setData(data);
    else {
      map.addSource('report', {type:'geojson', data});
      map.addLayer({id:'report-link', type:'line', source:'report', filter:['==', ['geometry-type'], 'LineString'], paint:{'line-color':'#f97316', 'line-width':2.5, 'line-dasharray':[2, 1.5], 'line-opacity':.9}});
      map.addLayer({id:'report-pulse', type:'circle', source:'report', filter:['==', ['geometry-type'], 'Point'], paint:{'circle-color':'rgba(0,0,0,0)', 'circle-stroke-color':'#f97316', 'circle-stroke-width':2, 'circle-radius':10, 'circle-stroke-opacity':.8}});
      map.addLayer({id:'report-node', type:'circle', source:'report', filter:['==', ['geometry-type'], 'Point'], paint:{'circle-color':'#ea580c', 'circle-radius':6, 'circle-stroke-color':'#fff', 'circle-stroke-width':2}});
    }
    geo.features.forEach(f => map.setFeatureState({source:'scan', id:f.properties.TOWNNAME}, {pick:three.includes(f.properties.TOWNNAME), dim:!three.includes(f.properties.TOWNNAME)}));
    for (const id of ['report-link','report-pulse','report-node']) map.setLayoutProperty(id, 'visibility', 'visible');
    const boxes = three.map(name => bounds(geo.features.find(f => f.properties.TOWNNAME === name)));
    const frameBox = [[Math.min(...boxes.map(b => b[0][0])), Math.min(...boxes.map(b => b[0][1]))], [Math.max(...boxes.map(b => b[1][0])), Math.max(...boxes.map(b => b[1][1]))]];
    map.fitBounds(frameBox, {padding:padding(), pitch:0, bearing:0, duration:reduced ? 0 : 1200});
    cancelAnimationFrame(pulse);
    if (reduced) return;
    // A ring breathes out of each district centre: three radar locks at once.
    const tick = now => {
      const t = (now % 1600) / 1600;
      map.setPaintProperty('report-pulse', 'circle-radius', 8 + t * 26);
      map.setPaintProperty('report-pulse', 'circle-stroke-opacity', .85 * (1 - t));
      pulse = requestAnimationFrame(tick);
    };
    pulse = requestAnimationFrame(tick);
  }
  function hideReportMap() {
    cancelAnimationFrame(pulse);
    if (!map || !geo) return;
    for (const id of ['report-link','report-pulse','report-node']) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'none');
    if (map.getSource('scan')) geo.features.forEach(f => map.setFeatureState({source:'scan', id:f.properties.TOWNNAME}, {pick:false, dim:false}));
  }
  // Panels slide out, swap their content, then slide back in.
  function swap(toReport) {
    const workspace = document.querySelector('.radar-workspace');
    workspace.classList.add('scan-swap');
    setTimeout(() => {
      workspace.classList.toggle('scan-report', toReport);
      left.scrollTop = right.scrollTop = 0;
      workspace.classList.remove('scan-swap');
      (toReport ? $('report-back') : $('scan-compare')).focus({preventScroll:true});
    }, reduced ? 0 : 320);
  }
  async function openReport() {
    try {
      if (!talent) {
        const response = await fetch('/static/district-talent.json');
        if (!response.ok) throw Error('talent');
        talent = await response.json();
      }
    } catch {status.textContent = '人才資料讀取失敗，請重新整理後再試。';return;}
    const three = ranking.slice(0, 3).map(item => item.name);
    renderReport(three);showReportMap(three);swap(true);
    status.textContent = `正在比較${three.join('、')}`;
  }
  function closeReport() {
    hideReportMap();swap(false);
    map.fitBounds(bounds(), {padding:padding(), pitch:0, bearing:0, duration:reduced ? 0 : 1000});
    status.textContent = '';
  }
  $('scan-compare').addEventListener('click', openReport);
  $('report-back').addEventListener('click', closeReport);

  async function start() {
    if (started) return;
    started = true;
    map = window.streetMap.getMap();
    if (!map) {started = false;return;}
    try {
      if (!geo) [geo, activity, stats] = await Promise.all(['/static/taichung-districts.geojson','/static/gcis-district-activity.json','/static/district-stats.json'].map(async url => {
        const response = await fetch(url);
        if (!response.ok) throw Error(url);
        return response.json();
      }));
    } catch {
      started = false;status.textContent = '商工資料讀取失敗，請重新整理後再試。';return;
    }
    intent = window.radarIntent || {};
    parseIntent(intent);renderCriteria();rank();
    addLayers();setVisible(true);
    window.campusMatching?.deactivate();window.headhunter?.deactivate();window.recruitment?.deactivate();
    const workspace = document.querySelector('.radar-workspace');
    if (!workspace.classList.contains('sidebar-collapsed')) $('sidebar-toggle').click();
    workspace.classList.add('scan-active');left.inert = false;right.inert = false;
    status.textContent = `正在掃描臺中 ${geo.features.length} 個行政區…`;
    map.fitBounds(bounds(), {padding:padding(), pitch:0, bearing:0, duration:reduced ? 0 : 1600});
    setTimeout(() => {paintScores(false);renderCards();right.classList.add('cards-in');}, reduced ? 0 : 900);
  }
  function stop() {
    cancelAnimationFrame(frame);hideReportMap();
    const workspace = document.querySelector('.radar-workspace');
    workspace.classList.remove('scan-active', 'scan-report');right.classList.remove('cards-in');left.inert = true;right.inert = true;
    if (workspace.classList.contains('sidebar-collapsed')) $('sidebar-toggle').click();
    setVisible(false);started = false;revealed = located = false;status.textContent = '';
    $('map-home').click();
  }
  $('scan-close').addEventListener('click', stop);
  // The map flies to the street pin first; waiting for that flight keeps it from cutting the city overview short.
  const ready = () => {if (revealed && located) start();};
  document.addEventListener('radar:revealed', () => {revealed = true;started = false;ready();});
  document.addEventListener('streetmap:location-changing', () => {located = false;});
  document.addEventListener('streetmap:location', () => {located = true;setTimeout(ready, reduced ? 0 : 400);});
  document.addEventListener('streetmap:location-error', () => {located = true;ready();});
  window.siteScan = {start, stop};
})();
