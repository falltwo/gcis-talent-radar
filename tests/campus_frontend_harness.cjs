/* Execute the shipped campus controller with a small deterministic DOM/map.
 * Fixtures below are contract examples, never substitute production data.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function environment() {
  const ids = new Map(), events = new Map(), requests = [], markers = [], popups = [];
  class Element {
    constructor(tag = 'div') {
      this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
      this.attributes = {}; this.listeners = {}; this.hidden = false;
      this.disabled = false; this.value = ''; this._text = ''; this._className = '';
      this.style = {setProperty() {}, removeProperty() {}};
      this.classList = {
        add: (...v) => {this._className = [...new Set([...this._className.split(/\s+/).filter(Boolean), ...v])].join(' ');},
        remove: (...v) => {this._className = this._className.split(/\s+/).filter(x => !v.includes(x)).join(' ');},
        contains: v => this._className.split(/\s+/).includes(v),
        toggle: (v, force) => {const on = force ?? !this.classList.contains(v); on ? this.classList.add(v) : this.classList.remove(v); return on;},
      };
    }
    set id(v) {this._id = v; ids.set(v, this);} get id() {return this._id || '';}
    set className(v) {this._className = v;} get className() {return this._className;}
    set textContent(v) {this._text = String(v); this.children = [];}
    get textContent() {return this._text + this.children.map(n => n.textContent || '').join('');}
    set innerHTML(html) {
      this.children = []; this._text = ''; const stack = [this];
      const tokens = html.match(/<[^>]+>|[^<]+/g) || [];
      for (const token of tokens) {
        if (token.startsWith('</')) {if (stack.length > 1) stack.pop(); continue;}
        if (token.startsWith('<')) {
          const match = token.match(/^<([\w-]+)/); if (!match) continue;
          const el = new Element(match[1]);
          for (const attr of token.slice(match[0].length, -1).matchAll(/([\w-]+)(?:="([^"]*)"|='([^']*)'|=([^\s>]+))?/g)) {
            el.setAttribute(attr[1], attr[2] ?? attr[3] ?? attr[4] ?? '');
          }
          stack.at(-1).append(el);
          if (!/^(input|br|hr|img|meta|link)$/i.test(match[1]) && !token.endsWith('/>')) stack.push(el);
        } else stack.at(-1)._text += token;
      }
    }
    setAttribute(k, v) {
      v = String(v); this.attributes[k] = v;
      if (k === 'id') this.id = v;
      if (k === 'class') this.className = v;
      if (k === 'value') this.value = v;
      if (k === 'hidden') this.hidden = true;
      if (k === 'checked') this.checked = true;
      if (k.startsWith('data-')) this.dataset[k.slice(5).replace(/-([a-z])/g, (_, a) => a.toUpperCase())] = v;
    }
    getAttribute(k) {return this.attributes[k] ?? null;}
    removeAttribute(k) {delete this.attributes[k];}
    append(...nodes) {for (let n of nodes) {if (typeof n === 'string') {const text = new Element('text'); text._text = n; n = text;} n.parentElement = this; this.children.push(n);}}
    prepend(...nodes) {for (const n of nodes) n.parentElement = this; this.children.unshift(...nodes);}
    insertBefore(n, reference) {n.parentElement=this;const index=this.children.indexOf(reference);if(index<0)this.children.push(n);else this.children.splice(index,0,n);}
    replaceChildren(...nodes) {this.children = []; this._text = ''; this.append(...nodes);}
    remove() {if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(n => n !== this);}
    matches(selector) {
      if (selector === 'dialog[open]') return this.tagName === 'DIALOG' && this.open;
      if (selector.startsWith('#')) return this.id === selector.slice(1);
      if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
      const attribute = selector.match(/^([\w-]+)?\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\]$/);
      if (attribute) return (!attribute[1] || this.tagName.toLowerCase() === attribute[1]) && this.getAttribute(attribute[2]) !== null && (!attribute[3] || this.getAttribute(attribute[2]) === attribute[3]);
      return this.tagName.toLowerCase() === selector;
    }
    querySelectorAll(selector) {
      const selectors = selector.split(',').map(s => s.trim()); const found = [];
      for (const child of this.children) {if (selectors.some(s => child.matches(s))) found.push(child); found.push(...child.querySelectorAll(selector));}
      return found;
    }
    querySelector(selector) {return this.querySelectorAll(selector)[0] || null;}
    closest(selector) {return selector === 'section.panel' ? chat : this.matches(selector) ? this : this.parentElement?.closest(selector);}
    addEventListener(type, fn) {(this.listeners[type] ||= []).push(fn);}
    emit(type, extra = {}) {const event = {type, target: this, currentTarget: this, preventDefault() {}, ...extra}; for (const fn of this.listeners[type] || []) fn(event);}
    click() {return this.emit('click');}
    focus() {} scrollIntoView() {} setCustomValidity(v) {this.validationMessage = v;}
    checkValidity() {return !this.validationMessage && (!this.id.includes('radius') || Number(this.value) >= 0.1);}
    reportValidity() {return this.checkValidity();}
  }
  const body = new Element('body'), workspace = new Element('section'); workspace.className = 'radar-workspace'; body.append(workspace);
  const chat = new Element('section'); chat.className = 'panel';
  for (const id of ['ask-title', 'radar-chat', 'city-stage', 'company-roles']) {const el = new Element(); el.id = id; (id === 'ask-title' ? chat : workspace).append(el);}
  ids.get('radar-chat').append(chat); ids.get('company-roles').textContent = 'CNC 技術員、品管人員';
  const document = {
    body, createElement: tag => new Element(tag), createTextNode: text => {const n = new Element('text'); n.textContent = text; return n;},
    getElementById: id => ids.get(id), querySelector: selector => body.querySelector(selector), querySelectorAll: selector => body.querySelectorAll(selector),
    addEventListener: (type, fn) => {(events.get(type) || events.set(type, []).get(type)).push(fn);},
  };
  const sources = new Map(), layers = new Map();
  const map = {
    addSource: (id, value) => sources.set(id, {...value, setData(data) {this.data = data;}}), getSource: id => sources.get(id), removeSource: id => sources.delete(id),
    addLayer: layer => layers.set(layer.id, layer), getLayer: id => layers.get(id), removeLayer: id => layers.delete(id),
    setPaintProperty() {}, fitBounds() {}, easeTo() {}, flyTo() {}, stop() {}, resize() {}, getCenter:()=>({lng:120.65,lat:24.2}),getZoom:()=>12,getPitch:()=>35,getBearing:()=>-15,getPadding:()=>({top:0,bottom:0,left:0,right:0}),isStyleLoaded: () => true,
    getContainer: () => ({clientHeight: 900,clientWidth:930}), once: (_, fn) => fn(), on() {}, off() {},
  };
  let location = {coordinates: [120.65, 24.2], district: '大雅區', road: '測試道路'};
  class Marker {
    constructor({element}) {this.el = element; markers.push(this);}
    setLngLat(coordinates) {this.coordinates = coordinates; return this;}
    addTo() {this.removed = false; return this;} getElement() {return this.el;} remove() {this.removed = true;}
  }
  class Popup {
    constructor() {popups.push(this);}
    setLngLat() {return this;} setDOMContent(el) {this.el = el; return this;} addTo() {return this;}
    getElement() {return this.el;} on(type, fn) {if (type === 'close') this.onClose = fn; return this;}
    remove() {this.removed = true; this.onClose?.();}
  }
  class LngLatBounds {extend() {return this;}}
  const window = {streetMap: {getMap: () => map, getLocation: () => location, closeCompany() {}, popupAnchor: () => 'bottom'}, radarFeatures: {select() {}}};
  const fetch = (url, options = {}) => new Promise((resolve, reject) => {requests.push({url: String(url), options, resolve, reject});options.signal?.addEventListener('abort',()=>reject(Object.assign(Error('Aborted'),{name:'AbortError'})),{once:true});});
  const context = {document, window, maplibregl: {Marker, Popup, LngLatBounds}, fetch, console, URL, URLSearchParams, Intl, AbortController,
    matchMedia: () => ({matches: true}), performance: {now: () => 10000}, requestAnimationFrame: () => 1, cancelAnimationFrame() {}, setTimeout, clearTimeout,
    sessionStorage: {getItem: () => null, setItem() {}, removeItem() {}}, localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
  };
  vm.createContext(context);
  for(const script of ['campus-camera.js','campus-insights.js','campus-matching.js'])vm.runInContext(fs.readFileSync(path.join(__dirname, '../ui/static/'+script), 'utf8'), context);
  return {ids, requests, markers, popups, sources, layers, window, workspace, chat,
    event: (type, detail) => Promise.all((events.get(type) || []).map(fn => fn({type, detail}))),
    setLocation: value => {location = value;},
    liveMarkers: () => markers.filter(marker => !marker.removed),
  };
}

const flush = async () => {for (let i = 0; i < 3; i++) await new Promise(resolve => setImmediate(resolve));};
const campus = (id = 'campus-a', longitude = 120.68) => ({campus_id: id, institution_id: 'school-a', institution_name: '契約測試大學', name: '正式校區',
  city: '臺中市', district: '西屯區', address: '臺中市測試路', latitude: 24.17, longitude, distance_km: 4.5,
  source_url: 'https://udb.moe.edu.tw/fixture', website: 'https://fixture.edu.tw',
  coordinate_status: 'VERIFIED_OFFICIAL_GEOMETRY',
  coordinate_reference: {point_type: 'CAMPUS_INTERIOR_REFERENCE', crs: 'EPSG:4326'},
  departments: [{department_id: 'dept-a', name: '機械工程學系', website: 'https://fixture.edu.tw/me', relation_type: 'SINGLE_OFFICIAL_CAMPUS', relation_label: '單一官方校區推定，非逐系教學校區核驗'}],
  unlocated_department_count: 0, matched_departments: [], unlocated_department_matches: [], match_scope: 'ALL'});
const answer = (items = [campus()]) => ({release_id: 'contract-fixture', academic_year: 114, total: items.length, items,
  verified_campus_count: 22, coverage_campus_count: 22, status: items.length ? 'OK' : 'NO_MATCH',
  source_as_of: '114學年度', search_type: 'CAMPUS_AND_DEPARTMENT_NAME_TEXT', distance_type: 'GREAT_CIRCLE',
  limitations: ['校園範圍內代表點，非校門。']});
async function respond(request, payload = answer(), status = 200) {request.resolve({ok: status >= 200 && status < 300, status, json: async () => payload}); await flush();}
const cases = {
  async actual_api_coordinates() {
    const e = environment(); e.window.campusMatching.toggle(); await flush();
    assert.equal(e.requests.length, 1);
    const url = new URL(e.requests[0].url, 'http://test');
    assert.equal(url.pathname, '/api/education/campuses');
    assert.equal(Number(url.searchParams.get('latitude')), 24.2); assert.equal(Number(url.searchParams.get('longitude')), 120.65);
    assert.equal(Number(url.searchParams.get('radius_km')), 15);
    assert.ok(!url.searchParams.get('q'), 'Do not silently turn a job title into a department match');
    await respond(e.requests[0]);
    assert.equal(e.liveMarkers().length, 1);
    assert.ok(e.layers.has('campus-radius-fill'), 'The official results keep the map radius overlay');
    assert.deepEqual(Array.from(e.liveMarkers()[0].coordinates), [120.68, 24.17], 'Use the API coordinate without origin offsets');
    assert.match(e.ids.get('campus-results').textContent, /契約測試大學/);
    assert.doesNotMatch(e.ids.get('campus-results').textContent, /虛構|展示距離/);
  },
  async stale_request_and_exit() {
    const e = environment(); e.window.campusMatching.toggle(); await flush(); const first = e.requests[0];
    await e.event('streetmap:location-changing'); e.setLocation({coordinates: [120.7, 24.1], district: '南區'});
    await e.event('streetmap:location'); await flush(); const second = e.requests[1]; assert.ok(second);
    await respond(second, answer([campus('new-campus', 120.72)]));
    await respond(first, answer([campus('old-campus', 120.61)]));
    assert.equal(e.liveMarkers().length, 1); assert.deepEqual(Array.from(e.liveMarkers()[0].coordinates), [120.72, 24.17]);
    e.window.campusMatching.deactivate(); assert.equal(e.liveMarkers().length, 0); assert.equal(e.sources.size, 0);
    assert.equal(e.ids.get('campus-panel').hidden, true); assert.equal(e.chat.hidden, false);
    e.window.campusMatching.toggle(); await flush(); const last = e.requests.at(-1); e.window.campusMatching.deactivate(); await respond(last);
    assert.equal(e.liveMarkers().length, 0, 'A late response must not reopen the map after leaving');
  },
  async unavailable_then_retry() {
    const e = environment(); e.window.campusMatching.toggle(); await flush();
    await respond(e.requests[0], {detail: '校園資料尚未匯入'}, 503);
    assert.equal(e.liveMarkers().length, 0); assert.ok(e.ids.get('campus-results-status').textContent);
    const retry = e.ids.get('campus-retry');
    if (retry) await retry.click(); else await e.ids.get('campus-filters').emit('submit');
    await flush(); assert.equal(e.requests.length, 2, 'The failure must allow another real API request');
    await respond(e.requests[1]); assert.equal(e.liveMarkers().length, 1);
  },
  async empty_and_radius_validation() {
    const e = environment(); e.window.campusMatching.toggle(); await flush(); await respond(e.requests[0], answer([]));
    assert.equal(e.liveMarkers().length, 0); assert.match(e.ids.get('campus-results-status').textContent, /沒有|查無|找不到|無符合/);
    e.ids.get('campus-radius').value = '0'; await e.ids.get('campus-filters').emit('submit'); await flush();
    assert.equal(e.requests.length, 1, 'Invalid radius must not create an API request');
    e.ids.get('campus-radius').value = '7.5'; await e.ids.get('campus-filters').emit('submit'); await flush();
    assert.equal(Number(new URL(e.requests[1].url, 'http://test').searchParams.get('radius_km')), 7.5);
    await respond(e.requests[1], answer([]));
  },
  async keyword_is_an_api_name_search() {
    const e = environment(); e.window.campusMatching.toggle(); await flush(); await respond(e.requests[0]);
    e.ids.get('campus-query').value = '機械工程';
    await e.ids.get('campus-filters').emit('submit'); await flush();
    const url = new URL(e.requests[1].url, 'http://test');
    assert.equal(url.pathname, '/api/education/campuses'); assert.equal(url.searchParams.get('q'), '機械工程');
    assert.equal(e.liveMarkers().length, 0, 'Old search results must disappear while the new query is pending');
    await respond(e.requests[1], answer([])); assert.equal(e.liveMarkers().length, 0);
  },
  async related_toggle_and_suggestions(){
    const e=environment();e.window.campusMatching.toggle();await flush();
    assert.equal(new URL(e.requests[0].url,'http://test').searchParams.get('include_related'),'true');
    await respond(e.requests[0],{...answer([]),suggestions:['資訊工程']});
    e.ids.get('campus-related').checked=false;
    await e.ids.get('campus-suggestions').querySelector('button').click();await flush();
    const url=new URL(e.requests[1].url,'http://test');
    assert.equal(url.searchParams.get('q'),'資訊工程');assert.equal(url.searchParams.get('include_related'),'false');assert.equal(url.searchParams.get('radius_km'),'15');
    await respond(e.requests[1],answer([]));e.window.campusMatching.deactivate();
  },
  async job_search_uses_the_same_field_and_shows_evidence() {
    const e=environment();e.window.campusMatching.toggle();await flush();await respond(e.requests[0]);
    e.ids.get('campus-query').value='軟體工程師';
    await e.ids.get('campus-filters').emit('submit');await flush();
    assert.equal(new URL(e.requests[1].url,'http://test').searchParams.get('q'),'軟體工程師');
    const selected=campus(), title='軟體設計工程師', source='https://collego.edu.tw/Highschool/MajorIntro?current_major_id=1';
    selected.related_departments=[{department_id:'cs',name:'資訊工程學系',career_matches:[{title,source_url:source}]}];
    await respond(e.requests[1],{...answer([selected]),search_type:'DEPARTMENT_CAREER',career_query:{roles:[title]}});
    assert.match(e.ids.get('campus-results-status').textContent,/軟體設計工程師/);
    await e.ids.get('campus-results').querySelector('button').click();
    const detail=e.popups.at(-1).getElement();
    assert.ok(detail.querySelectorAll('a').some(link=>link.href===source && link.textContent.includes(title)));
    e.window.campusMatching.deactivate();
  },
  async school_insights_are_scoped_and_cancelled(){
    const e=environment();e.window.campusMatching.toggle();await flush();const selected=campus();selected.matched_departments=selected.departments.map(d=>({...d,registry_listed:1}));
    selected.related_departments=[{department_id:'related',name:'資訊工程學系',website:'https://official.example/cs',registry_listed:0,location_status:'TEACHING_LOCATION_UNVERIFIED'}];
    selected.departments.push({department_id:'unrelated',name:'財務金融學系'});
    await respond(e.requests[0],answer([selected]));
    await e.ids.get('campus-results').querySelector('button').click();await flush();
    const panel=e.popups.at(-1).getElement();assert.match(panel.textContent,/機械工程學系/);assert.match(panel.textContent,/相關科系/);assert.match(panel.textContent,/資訊工程學系/);
    assert.match(panel.textContent,/名冊未列，招生狀態待查/);
    assert.equal(panel.querySelectorAll('small').filter(n=>n.textContent==='名冊未列，招生狀態待查').length,1,'Only the supplementary department needs the roster warning');
    assert.doesNotMatch(panel.textContent,/在學|人數|熱門|企業偏好|財務金融/);
    assert.equal(panel.querySelector('select'),null,'No study-scope filter remains');
    assert.equal(e.requests.length,1,'Showing department names must not fetch enrollment statistics');
    await panel.querySelector('.campus-return').click();assert.equal(e.popups.at(-1).removed,true);e.window.campusMatching.deactivate();
  },
  async popup_and_candidates_follow_the_origin() {
    const e = environment(); e.window.campusMatching.toggle(); await flush();
    const item = campus(); item.departments = []; item.unlocated_department_count = 1;
    item.unlocated_department_matches = [{department_id: 'pending-dept', name: '資訊工程學系', website: 'javascript:alert(1)'}];
    await respond(e.requests[0], answer([item]));
    await e.ids.get('campus-results').querySelector('button').click();

    const popup = e.popups.at(-1).getElement();
    assert.match(popup.textContent, /114 學年度/); assert.match(popup.textContent, /教學校區待核驗|實際教學校區待核驗/);
    assert.match(popup.textContent, /資訊工程學系/);assert.doesNotMatch(popup.textContent,/在學|人數/);
    const links = popup.querySelectorAll('a'); assert.ok(links.length > 0);
    assert.ok(links.every(link => !link.href.startsWith('javascript:')), 'Source text cannot become a script link');
    await popup.querySelector('.campus-add').click(); assert.match(e.ids.get('campus-basket-summary').textContent, /1/);
    await popup.querySelector('.campus-add').click(); assert.match(e.ids.get('campus-basket-summary').textContent, /0/);
    await popup.querySelector('.campus-add').click();
    await e.event('streetmap:location-changing'); assert.match(e.ids.get('campus-basket-summary').textContent, /0/);
    assert.equal(e.liveMarkers().length, 0); assert.equal(e.sources.size, 0);
  },
  async school_phone_is_plain_text_with_source_below(){
    const e=environment();e.window.campusMatching.toggle();await flush();const item=campus();
    item.school_phone={status:'AVAILABLE',label:'學校總機',display:'04-2451-7250',tel_uri:'tel:+886424517250',source_url:'https://udb.moe.edu.tw/fixture.csv',checked_at:'2026-11-03T16:00:00+08:00'};
    await respond(e.requests[0],answer([item]));await e.ids.get('campus-results').querySelector('button').click();
    let panel=e.popups.at(-1).getElement();
    assert.match(panel.textContent,/學校總機/);assert.match(panel.textContent,/04-2451-7250/);assert.doesNotMatch(panel.textContent,/查核|2026-11-03/);
    assert.ok(panel.querySelectorAll('a').every(a=>!a.href.startsWith('tel:')));
    assert.match(panel.querySelector('.campus-official-links').textContent,/電話來源：教育部名錄/);
    assert.doesNotMatch(panel.querySelector('.campus-official-links').textContent,/查核|2026-11-03/);
    assert.doesNotMatch(panel.querySelector('dl').textContent,/電話來源|2026-11-03/);
    await panel.querySelector('.campus-return').click();
    item.school_phone.tel_uri='javascript:alert(1)';
    await e.ids.get('campus-results').querySelector('button').click();panel=e.popups.at(-1).getElement();
    assert.ok(panel.querySelectorAll('a').every(a=>!a.href.startsWith('javascript:')));
    e.window.campusMatching.deactivate();
  },
};
(async () => {const name = process.argv[2]; assert.ok(cases[name], `Unknown case: ${name}`); await cases[name](); console.log(`PASS ${name}`);})().catch(error => {console.error(error); process.exitCode = 1;});
