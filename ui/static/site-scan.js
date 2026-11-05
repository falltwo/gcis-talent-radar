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
  let revealed = false, located = false, step = 'intro', navigationEpoch = 0, intentKey = null;
  let comparedDistricts = [], selectedDistrict = null;

  const stage = $('city-stage');
  const left = document.createElement('aside');
  left.className = 'scan-side scan-left';left.setAttribute('aria-label','選址條件');left.inert = true;
  left.innerHTML = `
    <nav class="scan-navigation" aria-label="選址流程"><button type="button" id="scan-back">← 上一步：修改需求</button><span id="scan-step-label">1 / 3 · 商工排名</span></nav>
    <div class="scan-pane scan-report-only"><h3>1. 人才供給與職缺需求</h3><div class="scan-body"><div id="report-supply"></div><p class="scan-note" id="report-supply-note"></p></div></div>
    <div class="scan-pane scan-report-only"><h3>2. 附近的關鍵學校</h3><div class="scan-body"><div id="report-schools"></div></div></div>
    <div class="scan-pane scan-rank-only"><h3>從需求擷取的條件</h3><div class="scan-body"><div class="scan-tags" id="scan-tags"></div><p class="scan-note" id="scan-intent-note"></p></div></div>
    <div class="scan-pane scan-rank-only"><h3>商工行政環境篩選</h3><div class="scan-body"><div id="scan-criteria"></div><p class="scan-note" id="scan-gap"></p></div></div>
    <button type="button" class="scan-close" id="scan-close">結束掃描，回到街區地圖</button>`;
  const right = document.createElement('aside');
  right.className = 'scan-side scan-right';right.setAttribute('aria-label','推薦建廠熱區');right.inert = true;
  right.innerHTML = `
    <div class="scan-pane scan-report-only"><h3>3. 職缺開出的月薪</h3><div class="scan-body"><div id="report-salary"></div><p class="scan-note">雇主在就業通刊登的薪資，不是求職者的期望薪資。</p></div></div>
    <div class="scan-pane scan-report-only"><h3>4. 招募建議 <span id="report-advice-source">系統依上面數字產生，非 AI</span></h3><div class="scan-body"><ul class="report-advice" id="report-advice"></ul>
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
  const plan = document.createElement('section');
  plan.className = 'hire-plan';plan.id = 'hire-plan';plan.hidden = true;plan.setAttribute('aria-labelledby', 'hire-plan-title');
  plan.innerHTML = `<header><div><small>已選定設廠地點</small><h3 id="hire-plan-title"></h3><p id="hire-plan-place"></p></div><button type="button" id="hire-plan-close" aria-label="返回人才比較">×</button></header>
    <button type="button" class="scan-previous" id="hire-plan-back">← 上一步：人才比較</button><p class="hire-plan-lead">沿用三區戰報的數字分配三種人才來源，點卡片按鈕會用這個地點開啟功能。</p><ol class="hire-cards" id="hire-plan-list"></ol>
    <p class="scan-note" id="hire-plan-note"></p>`;
  stage.append(plan);
  const featureBack = document.createElement('button');featureBack.type='button';featureBack.id='scan-feature-back';featureBack.className='scan-feature-back';featureBack.textContent='← 上一步：招募管道';featureBack.hidden=true;stage.append(featureBack);
  function setStep(next) {
    step=next;plan.hidden=next!=='plan';featureBack.hidden=next!=='feature';
    $('scan-back').textContent=next==='report'?'← 上一步：商工排名':'← 上一步：修改需求';
    $('scan-step-label').textContent=next==='report'?'2 / 3 · 人才比較':'1 / 3 · 商工排名';
    $('scan-compare').disabled=false;
  }
  function closeFeatures() {window.campusMatching?.deactivate();window.headhunter?.deactivate();window.recruitment?.deactivate();}
  function resumeReport() {
    closeFeatures();started=true;addLayers();setVisible(true);paintScores(true);
    const workspace=document.querySelector('.radar-workspace');
    if(!workspace.classList.contains('sidebar-collapsed'))$('sidebar-toggle').click();
    workspace.classList.add('scan-active','scan-report');left.inert=right.inert=false;right.classList.add('cards-in');
    renderReport(comparedDistricts);showReportMap(comparedDistricts);setStep('report');
    $('scan-back').focus({preventScroll:true});
  }
  function back() {
    navigationEpoch++;cancelAnimationFrame(frame);
    document.querySelector('.radar-workspace').classList.remove('scan-swap');
    if(step==='feature'){closeFeatures();setStep('plan');$('hire-plan-back').focus({preventScroll:true});return;}
    if(step==='plan'){resumeReport();return;}
    if(step==='report'){closeReport();return;}
    if(step==='rank'){stop();$('replay-intro').click();}
  }
  $('scan-back').addEventListener('click',back);$('hire-plan-back').addEventListener('click',back);
  $('hire-plan-close').addEventListener('click',back);featureBack.addEventListener('click',back);
  for(const id of ['campus-exit','posting-exit','hunter-exit'])$(id)?.addEventListener('click',()=>{if(step==='feature')back();});
  $('replay-intro').addEventListener('click',()=>{if(step!=='intro')stop();});

  const GAP_LABELS = {transport:'交通', land:'地價與廠房', utilities:'水電與環評', other:'部分條件'};
  let aiIntent = null;
  // `ai` is the /api/site-intent answer; without it (no key, timeout, error) the keyword rules below decide.
  function parseIntent(raw, ai) {
    const text = raw?.text || '', preference = raw?.preference || '';
    aiIntent = ai?.source === 'llm' ? ai.intent : null;
    industry = aiIntent?.industry || INDUSTRY_WORDS.find(([word]) => text.includes(word))?.[1] || null;
    checked = Object.fromEntries(CRITERIA.map(c => [c.id, true]));
    boosted = Object.fromEntries(CRITERIA.map(c => [c.id, aiIntent ? aiIntent.emphasis.includes(c.id) : c.words.some(word => text.includes(word))]));
    if (PREFERENCE[preference]) boosted[PREFERENCE[preference]] = true;
    const tags = [];
    tags.push(industry ? ['產業', industry] : ['產業', '未判斷，看全部製造業']);
    if (preference) tags.push(['偏好', preference]);
    CRITERIA.filter(c => boosted[c.id]).forEach(c => tags.push(['加重', c.label]));
    if (aiIntent?.role) tags.push(['職務', aiIntent.role]);
    if (aiIntent?.senior_role) tags.push(['關鍵職務', aiIntent.senior_role]);
    if (aiIntent?.hires) tags.push(['人數', `${aiIntent.hires} 人`]);
    (aiIntent?.related_industries || []).forEach(name => tags.push(['相關產業', name]));
    // The user's own words come first, so the gap note shows exactly what was read but not used.
    const missing = aiIntent ? (aiIntent.unsupported_phrases?.length ? aiIntent.unsupported_phrases : aiIntent.unsupported.map(key => GAP_LABELS[key] || key))
      : NO_DATA_WORDS.filter(word => text.includes(word)).concat(preference === '靠近交通樞紐' ? ['交通樞紐'] : []);
    $('scan-tags').replaceChildren(...tags.map(([kind, value]) => {
      const tag = document.createElement('span');tag.className = 'scan-tag';
      tag.innerHTML = '<small></small><b></b>';tag.firstChild.textContent = kind;tag.lastChild.textContent = value;
      return tag;
    }));
    $('scan-intent-note').textContent = !text ? '沒有輸入文字，只依偏好按鈕設定。'
      : aiIntent?.uncodable_question ? `「${text}」・AI 判斷不出產業，先看全部製造業。${aiIntent.uncodable_question}`
      : aiIntent ? `「${text}」・AI 依主計總處行業分類擷取，只從固定選項挑；排名數字由系統計算`
      : `「${text}」・關鍵字擷取（AI 這次沒有回應）`;
    $('scan-gap').textContent = !missing.length ? '' : aiIntent?.unsupported_phrases?.length
      ? `「${[...new Set(missing)].join('」「')}」：沒有這方面的資料，這次未納入排名。`
      : `沒有${[...new Set(missing)].join('、')}的資料，這次未納入排名。`;
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
      // Related industries (other lines, outsourced processes) count as part of the cluster.
      const wanted = [industry, ...(aiIntent?.related_industries || [])].filter(Boolean);
      if (wanted.length) {
        const known = wanted.map(name => factories[name]).filter(count => count !== null && count !== undefined);
        return known.length ? known.reduce((sum, count) => sum + count, 0) : null;
      }
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
      const clusterNames = [industry, ...(aiIntent?.related_industries || [])].filter(Boolean);
      row.querySelector('b').textContent = c.id === 'cluster' && clusterNames.length ? `${c.label}（${clusterNames.join('＋')}）` : c.label;
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
  // The ETL picks an inside point far from the edges, so the dot never lands outside or on a border.
  function centre(name) {
    if (talent?.districts[name]?.label_point) return talent.districts[name].label_point;
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
  // Small-number rule: health agencies suppress rates built on counts under ten (e.g. Washington DOH
  // small-numbers guideline), so a district with fewer postings than this is not ranked on the ratio.
  const MIN_POSTINGS = 10;
  // Demand and supply share one commuting ring: both count the district plus neighbours fading to zero at 10 km.
  const nearby = d => ({postings: d.postings_nearby ?? d.postings, openings: d.openings_nearby ?? d.openings});
  const demandRatio = d => d.graduates_nearby && nearby(d).postings >= MIN_POSTINGS ? nearby(d).openings / d.graduates_nearby : null;
  function renderReport(three) {
    const rows = three.map(name => ({name, ...talent.districts[name], ...nearby(talent.districts[name])}));
    rows.forEach(row => {row.thin = row.postings < MIN_POSTINGS;row.ratio = demandRatio(row);});
    const order = rows.filter(row => row.ratio !== null).sort((a, b) => a.ratio - b.ratio);
    const level = row => row.thin ? '職缺樣本太少' : row.ratio === null ? '附近沒有相關科系' : order.length < 2 ? '' : row === order[0] ? '三區中較容易' : row === order[order.length - 1] ? '三區中較難' : '居中';
    const maxGrad = Math.max(...rows.map(r => r.graduates_nearby)), maxOpen = Math.max(...rows.map(r => r.openings));
    $('report-supply').replaceChildren(...rows.map(row => {
      const [box, head] = section(row.name);
      const tag = document.createElement('span');tag.className = 'report-level' + (row === order[0] ? ' is-easy' : '');tag.textContent = level(row);head.append(tag);
      const ratio = document.createElement('p');ratio.className = 'report-ratio';
      ratio.textContent = row.thin ? `附近製造類職缺只有約 ${row.postings} 筆，樣本太少，不比較招募壓力` : row.ratio === null ? `區內和離區界 ${talent.radius_km} 公里內都沒有大專相關科系` : `每位畢業生對應 ${row.ratio.toFixed(2)} 個職缺需求・區內學校 ${row.graduates_in_district.toLocaleString()} 人`;
      const pick = document.createElement('button');pick.type = 'button';pick.className = 'report-pick';
      pick.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M1 12h4M19 12h4"/></svg><span></span>';
      pick.lastChild.textContent = `選定${row.name}設廠並招人`;
      pick.addEventListener('click', () => choose(row.name));
      box.append(bar('相關科系畢業生（加權）', row.graduates_nearby, maxGrad, '人', 'is-supply'), bar('製造類職缺需求（加權）', row.openings, maxOpen, '人', 'is-demand'), ratio, pick);
      return box;
    }));
    $('report-supply-note').textContent = `畢業生：大專校院機械、電機等相關科系 ${talent.academic_year} 學年畢業生，不含高職。區內的學校全數計入；區外的學校依離區界的距離打折，${talent.radius_km / 2} 公里算一半，${talent.radius_km} 公里以外不算。職缺：就業通 ${talent.jobs_snapshot} 快照的技術、製造、工程類需求人數，跟畢業生用同一個通勤圈：鄰區職缺依該區代表點到區界的距離打折。沒有各區求職者人數的資料，所以這不是求職求才比。`;
    $('report-schools').replaceChildren(...rows.map(row => {
      const [box] = section(row.name);
      const list = document.createElement('ul');list.className = 'report-school-list';
      const top = row.schools.slice().sort((a, b) => b.graduates * b.weight - a.graduates * a.weight).slice(0, 2);
      if (!top.length) {const li = document.createElement('li');li.textContent = `區內和離區界 ${talent.radius_km} 公里內沒有大專校院相關科系`;list.append(li);}
      top.forEach(school => {
        const li = document.createElement('li');li.innerHTML = '<b></b><small></small>';
        li.firstChild.textContent = short(school.name);
        li.lastChild.textContent = `${school.km ? `${school.district}・離區界 ${school.km} 公里` : '在區內'}・相關科系 ${school.graduates} 人・${school.top_departments.slice(0, 2).join('、')}`;
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
    rows.filter(row => row.thin).forEach(row => advice.push(`${row.name}附近的製造類職缺只有約 ${row.postings} 筆，樣本太少，看不出招募壓力；當地製造業需求可能不大，要另外確認。`));
    rows.filter(row => !row.thin && row.ratio === null).forEach(row => advice.push(`${row.name}區內和附近都沒有大專相關科系，新鮮人要從外區通勤，比較適合用刊登召募找有經驗的人。`));
    // A school counts as shared only when it is in one district and close (weight >= .5) to the other.
    three.forEach((a, i) => three.slice(i + 1).forEach(b => {
      const own = (x, y) => talent.districts[x].schools.filter(s => s.km === 0 && talent.districts[y].schools.some(t => t.name === s.name && t.weight >= .5)).map(s => short(s.name));
      const both = [...own(a, b), ...own(b, a)];
      if (both.length) advice.push(`${a}和${b}距離近，${both.slice(0, 2).join('、')}在兩區的通勤範圍內，選其中一區也能接觸另一區的學校。`);
    }));
    const floors = rows.map(r => r.salary_floor_median).filter(Boolean);
    if (floors.length > 1) advice.push(new Set(floors).size === 1
      ? `三區開出的起薪中位數都是 ${floors[0].toLocaleString()} 元，起薪不是區分因素。`
      : `起薪中位數最高的是${rows.find(r => r.salary_floor_median === Math.max(...floors)).name}（${Math.max(...floors).toLocaleString()} 元），在那裡招人起薪要開得比較高。`);
    const caveat = '這只看新鮮人供給和公開職缺；沒有求職者人數、期望薪資和地價資料，最後仍要實地評估。';
    const showAdvice = (lines, source) => {
      $('report-advice').replaceChildren(...[...lines, caveat].map(text => {const li = document.createElement('li');li.textContent = text;return li;}));
      $('report-advice-source').textContent = source;
    };
    showAdvice(advice, '系統依上面數字產生，非 AI');
    askAdvice(rows, three);
    $('report-source').textContent = `資料：${talent.sources.graduates}；${talent.sources.campuses}；${talent.sources.jobs}。`;
  }
  // The facts are the numbers already on screen; the model may only refer to them as {f1}, {f2}...
  function adviceFacts(rows, three) {
    // `required` facts are the comparison the report is about; the advice is discarded if any is left out.
    const facts = [], add = (label, value, required = false) => facts.push({id:`f${facts.length + 1}`, label:label.slice(0, 40), value:String(value).slice(0, 40), required});
    rows.forEach(row => {
      add(`${row.name}相關科系畢業生（加權）`, `${row.graduates_nearby.toLocaleString()} 人`);
      // A number is required where there is one; for a thin sample the head count itself is what must be said.
      add(`${row.name}附近製造類職缺需求（加權）${row.thin ? '（樣本太少）' : ''}`, `${row.openings.toLocaleString()} 人（${row.postings} 筆）`, row.thin);
      if (!row.thin) add(`${row.name}每位畢業生對應的職缺需求`, row.ratio === null ? '附近沒有相關科系' : row.ratio.toFixed(2), row.ratio !== null);
      const schools = row.schools.filter(x => x.weight >= .5).sort((a, b) => b.graduates * b.weight - a.graduates * a.weight).slice(0, 2).map(x => short(x.name));
      if (schools.length) add(`${row.name}附近主要學校`, schools.join('、'));
      if (row.salary_floor_median) add(`${row.name}起薪中位數`, `${row.salary_floor_median.toLocaleString()} 元`);
    });
    three.forEach((a, i) => three.slice(i + 1).forEach(b => {
      const own = (x, y) => talent.districts[x].schools.filter(t => t.km === 0 && talent.districts[y].schools.some(u => u.name === t.name && u.weight >= .5)).map(t => short(t.name));
      const both = [...own(a, b), ...own(b, a)];
      if (both.length) add(`${a}與${b}共同通勤範圍內的學校`, both.slice(0, 2).join('、'));
    }));
    return facts;
  }
  async function askAdvice(rows, three) {
    const request = navigationEpoch;
    try {
      const response = await fetch('/api/site-advice', {method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({districts:three, industry:industry, role:aiIntent?.role || null, facts:adviceFacts(rows, three)})});
      const result = response.ok ? await response.json() : null;
      if (request !== navigationEpoch || result?.source !== 'llm') return;
      const caveat = '這只看新鮮人供給和公開職缺；沒有求職者人數、期望薪資和地價資料，最後仍要實地評估。';
      $('report-advice').replaceChildren(...[...result.sentences, caveat].map(text => {const li = document.createElement('li');li.textContent = text;return li;}));
      $('report-advice-source').textContent = 'AI 依上面數字整理，數字由系統填入';
    } catch {}
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
    const request=navigationEpoch;
    setTimeout(() => {
      if(request!==navigationEpoch||!started)return;
      workspace.classList.toggle('scan-report', toReport);
      left.scrollTop = right.scrollTop = 0;
      workspace.classList.remove('scan-swap');
      (toReport ? $('report-back') : $('scan-compare')).focus({preventScroll:true});
    }, reduced ? 0 : 320);
  }
  async function openReport() {
    const request=navigationEpoch;$('scan-compare').disabled=true;
    try {
      if (!talent) {
        const response = await fetch('/static/district-talent.json?v=20261106-ring1');
        if (!response.ok) throw Error('talent');
        talent = await response.json();
      }
    } catch {if(request===navigationEpoch){status.textContent = '人才資料讀取失敗，請再試一次。';$('scan-compare').disabled=false;}return;}
    if(request!==navigationEpoch||!started)return;
    const three = ranking.slice(0, 3).map(item => item.name);
    comparedDistricts=three;setStep('report');renderReport(three);showReportMap(three);swap(true);
    status.textContent = `正在比較${three.join('、')}`;
  }
  function closeReport() {
    setStep('rank');hideReportMap();swap(false);
    map.fitBounds(bounds(), {padding:padding(), pitch:0, bearing:0, duration:reduced ? 0 : 1000});
    status.textContent = '';
  }
  // Picking a district moves the street map there; the three hiring features read that location on their own.
  const FEATURES = {campus:'校園人才媒合', posting:'刊登召募', hunter:'獵頭Agent'};
  // ponytail: keyword rules for what each feature is told to look for; they only fill fields the user can still edit.
  const ROLE_WORDS = [['CNC','CNC 技術員'],['焊接','焊接技術員'],['模具','模具技術員'],['品管','品管人員'],['作業員','作業員'],['技術員','技術員']];
  const SENIOR_WORDS = [['廠長','廠長'],['主管','生產主管'],['工程師','工程師']];
  const DEPT_FOR = {'機械設備業':'機械','金屬製品業':'機械','汽車及其零件業':'機械','其他運輸工具及其零件業':'機械','產業用機械設備維修及安裝業':'機械','電子零組件業':'電機','電腦電子產品及光學製品業':'電機','電力設備及配備業':'電機','塑膠製品業':'化工','橡膠製品業':'化工','其他化學製品業':'化工'};
  function carryOver(name) {
    const text = intent?.text || '';
    const field = industry ? industry.replace(/業$/, '') : '';
    const role = aiIntent?.role || ROLE_WORDS.find(([word]) => text.toUpperCase().includes(word))?.[1] || '';
    const senior = aiIntent?.senior_role || SENIOR_WORDS.find(([word]) => text.includes(word))?.[1];
    return {
      district:name, place:`${name}${$('city-road').value}`, role,
      department: DEPT_FOR[industry] || (text.includes('電') ? '電機' : '機械'),
      senior: aiIntent?.senior_role ? senior : senior ? (senior === '工程師' && field ? `${field.replace(/設備$/, '')}工程師` : senior) : (field ? `${field.replace(/設備$/, '')}工程師` : '製程工程師'),
      salary: talent.districts[name].salary_floor_median,
    };
  }
  // Each feature resets its own fields when it opens, so the values go in on the next frame.
  function fill(key, carry) {
    const set = (id, value) => {const el = $(id);if (!el || !value) return;el.value = value;el.dispatchEvent(new Event('input', {bubbles:true}));};
    if (key === 'campus') {set('campus-query', carry.department);return;}
    requestAnimationFrame(() => {
      if (key === 'posting') {
        set('posting-role', carry.role);set('posting-address', carry.place);
        set('posting-brief', `在${carry.district}設廠，想招${carry.role || '現場技術人員'}${carry.salary ? `；當地製造類職缺起薪中位數 ${carry.salary.toLocaleString()} 元，薪資請參考` : ''}`);
      } else {
        // The agent checks for live mode after it opens and then writes its own sample query, so
        // re-apply ours for two seconds unless the user has started typing something else.
        const defaults = ['CNC 技術員', '找會 Python 的軟體工程師，在台中'];
        const apply = () => {if (defaults.includes($('hunter-job').value) || $('hunter-job').value === carry.senior) {set('hunter-job', carry.senior);$('hunter-tag').textContent = carry.senior;}};
        apply();[300, 800, 1500, 2200].forEach(delay => setTimeout(apply, delay));
      }
    });
  }
  // ponytail: relative cut-off (the city median ratio) so the order survives changes in how the ratio is counted;
  // the rule itself is still open in issue #39.
  function ratioMedian() {
    const all = Object.values(talent.districts).map(demandRatio).filter(r => r !== null).sort((a, b) => a - b);
    return all.length ? all[Math.floor(all.length / 2)] : null;
  }
  function channels(name) {
    const row = talent.districts[name], ratio = demandRatio(row);
    const schools = row.schools.filter(s => s.weight >= .5).sort((a, b) => b.graduates * b.weight - a.graduates * a.weight).slice(0, 2).map(s => short(s.name));
    const list = [
      {key:'campus', who:'新鮮人', big: row.graduates_nearby ? row.graduates_nearby.toLocaleString() + ' 人' : '0 人', label:'附近相關科系畢業生（加權）',
        why: schools.length ? `主要來源：${schools.join('、')}` : '附近沒有大專相關科系，要從外區找', rank: ratio === null ? 2 : ratio < ratioMedian() ? 0 : 1},
      {key:'posting', who:'一般求職者', big: nearby(row).openings.toLocaleString() + ' 人', label:'附近製造類職缺需求（加權）',
        why: row.salary_floor_median ? `起薪中位數 ${row.salary_floor_median.toLocaleString()} 元，開薪可以參考` : '沒有月薪刊登可以參考', rank: ratio === null || ratio >= ratioMedian() ? 0 : 1},
      {key:'hunter', who:'關鍵人才', big:'不分地點', label:'工程師、主管等難找的職位',
        why:'由獵頭 Agent 主動搜尋與接觸', rank:2},
    ];
    return {ratio, list:list.sort((a, b) => a.rank - b.rank)};
  }
  // Heat colours fade before the camera dives, so the city overview does not cut straight to streets.
  function fadeHeat(done) {
    if (reduced || !map?.getSource('scan')) return done();
    cancelAnimationFrame(frame);cancelAnimationFrame(pulse);
    for (const id of ['report-link','report-pulse','report-node']) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'none');
    const begin = performance.now();
    const step = now => {
      const t = Math.min(1, (now - begin) / 400);
      geo.features.forEach(f => map.setFeatureState({source:'scan', id:f.properties.TOWNNAME}, {lit:1 - t}));
      if (t < 1) frame = requestAnimationFrame(step); else done();
    };
    frame = requestAnimationFrame(step);
  }
  function choose(name) {
    const request=++navigationEpoch;selectedDistrict=name;
    const road = activity.districts[name]?.top_road;
    const district = $('city-district');
    district.value = name;district.dispatchEvent(new Event('change'));
    if (road && [...$('city-road').options].some(option => option.value === road)) $('city-road').value = road;
    const {ratio, list} = channels(name);
    $('hire-plan-title').textContent = `${name} → 招募管道分配`;
    $('hire-plan-place').textContent = `定位：${$('city-road').value}（近一年公司設立登記最多的道路，可在左側改選）`;
    $('hire-plan-list').replaceChildren(...list.map((item, index) => {
      const card = document.createElement('li');card.className = 'hire-card' + (index === 0 ? ' is-first' : '');
      card.style.setProperty('--delay', (reduced ? 0 : 400 + index * 90) + 'ms');
      card.innerHTML = '<header><b></b></header><strong></strong><p></p><small></small><em></em><button type="button"></button>';
      const carry = carryOver(name);
      card.querySelector('em').textContent = '會帶入：' + {campus:`${name}、搜尋「${carry.department}」相關科系`, posting:`${carry.place}${carry.role ? `、${carry.role}` : ''}${carry.salary ? `、起薪參考 ${carry.salary.toLocaleString()} 元` : ''}`, hunter:`職缺「${carry.senior}」`}[item.key];
      card.querySelector('b').textContent = item.who;
      card.querySelector('strong').textContent = item.big;
      card.querySelector('p').textContent = item.label;
      card.querySelector('small').textContent = item.why;
      card.querySelector('button').textContent = `開啟${FEATURES[item.key]} →`;
      card.querySelector('button').addEventListener('click', () => {
        setStep('feature');
        const carry = carryOver(name);
        // Campus matching searches as soon as it opens, so its query has to be set first.
        if (item.key === 'campus') fill('campus', carry);
        document.querySelector(`.primary-feature-button[data-feature="${FEATURES[item.key]}"]`)?.click();
        if (item.key !== 'campus') fill(item.key, carry);
      });
      return card;
    }));
    $('hire-plan-note').textContent = `順序依「每位畢業生對應的職缺需求」${ratio === null ? (nearby(talent.districts[name]).postings < MIN_POSTINGS ? '（職缺樣本太少，無法計算）' : '（附近沒有學校）') : `（${ratio.toFixed(2)}）`}排：低於全市中位數（${ratioMedian()?.toFixed(2)}）先找學校；高於中位數、附近沒有學校或職缺樣本太少就先刊登。這是展示用的規則，不是預測招募成效。`;
    fadeHeat(() => {
      if(request!==navigationEpoch)return;
      stop({home:false,keepJourney:true});
      $('sidebar-location').requestSubmit();
      setStep('plan');
      plan.querySelector('.hire-card button')?.focus({preventScroll:true});
    });
  }
  $('scan-compare').addEventListener('click', openReport);
  $('report-back').addEventListener('click', back);

  async function start() {
    if (started) return;
    started = true;const request=++navigationEpoch;setStep('rank');
    map = window.streetMap.getMap();
    if (!map) {started = false;return;}
    try {
      if (!geo) [geo, activity, stats] = await Promise.all(['/static/taichung-districts.geojson','/static/gcis-district-activity.json?v=20261105-road1','/static/district-stats.json'].map(async url => {
        const response = await fetch(url);
        if (!response.ok) throw Error(url);
        return response.json();
      }));
    } catch {
      if(request===navigationEpoch){started = false;status.textContent = '商工資料讀取失敗，請重新整理後再試。';}return;
    }
    if(request!==navigationEpoch||!started)return;
    intent = window.radarIntent || {};
    const nextKey=JSON.stringify(intent);
    if(nextKey!==intentKey){
      // The parse started when the user pressed Analyze, so it has had the whole transition to finish.
      const ai=await Promise.race([window.radarIntentParse||Promise.resolve(null),new Promise(done=>setTimeout(()=>done(null),1500))]);
      if(request!==navigationEpoch||!started)return;
      parseIntent(intent,ai);intentKey=nextKey;comparedDistricts=[];selectedDistrict=null;
    }
    renderCriteria();rank();
    addLayers();setVisible(true);
    window.campusMatching?.deactivate();window.headhunter?.deactivate();window.recruitment?.deactivate();
    const workspace = document.querySelector('.radar-workspace');
    if (!workspace.classList.contains('sidebar-collapsed')) $('sidebar-toggle').click();
    workspace.classList.add('scan-active');left.inert = false;right.inert = false;
    status.textContent = `正在掃描臺中 ${geo.features.length} 個行政區…`;
    map.fitBounds(bounds(), {padding:padding(), pitch:0, bearing:0, duration:reduced ? 0 : 1600});
    setTimeout(() => {if(request!==navigationEpoch||!started)return;paintScores(false);renderCards();right.classList.add('cards-in');}, reduced ? 0 : 900);
  }
  function stop({home = true,keepJourney = false} = {}) {
    navigationEpoch++;if(!keepJourney)setStep('intro');
    cancelAnimationFrame(frame);hideReportMap();
    const workspace = document.querySelector('.radar-workspace');
    workspace.classList.remove('scan-active', 'scan-report','scan-swap');right.classList.remove('cards-in');left.inert = true;right.inert = true;
    if (workspace.classList.contains('sidebar-collapsed')) $('sidebar-toggle').click();
    setVisible(false);started = false;revealed = located = false;status.textContent = '';
    if (home) $('map-home').click();
  }
  $('scan-close').addEventListener('click', () => stop());
  // The map flies to the street pin first; waiting for that flight keeps it from cutting the city overview short.
  const ready = () => {if (revealed && located) start();};
  document.addEventListener('radar:revealed', () => {revealed = true;started = false;ready();});
  document.addEventListener('streetmap:location-changing', () => {located = false;});
  document.addEventListener('streetmap:location', () => {located = true;setTimeout(ready, reduced ? 0 : 400);});
  document.addEventListener('streetmap:location-error', () => {located = true;ready();});
  window.siteScan = {start, stop, back};
})();
