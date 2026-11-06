const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {environment}=require('../campus_frontend_harness.cjs');
const source=fs.readFileSync(path.join(__dirname,'../../ui/static/site-scan.js'),'utf8');
const flush=async()=>{for(let i=0;i<4;i++)await new Promise(r=>setImmediate(r));};
function setup(transformStats){
 const e=environment([]),timers=[];let replayed=0;
 const launched=[];const originalQuery=e.document.querySelector;
 const buttons=new Map(['校園人才媒合','刊登召募','獵頭Agent'].map(name=>{const b=e.document.createElement('button');b.addEventListener('click',()=>launched.push(name));return[name,b];}));
 e.document.querySelector=selector=>{const match=selector.match(/^\.primary-feature-button\[data-feature="(.+)"\]$/);return match?buttons.get(match[1]):originalQuery(selector);};
 const proto=Object.getPrototypeOf(e.workspace);
 Object.defineProperties(proto,{firstChild:{get(){return this.children[0];}},lastChild:{get(){return this.children.at(-1);}}});
 for(const id of ['city-district','city-road','sidebar-toggle','sidebar-location','map-home','replay-intro','campus-exit','posting-exit','hunter-exit']){
  const n=e.document.createElement('button');n.id=id;e.workspace.append(n);
 }
 e.ids.get('city-road').value='中清路三段';e.ids.get('city-road').options=[{value:'中清路三段'}];
 for(const n of e.ids.values())n.dispatchEvent=()=>{};
 e.ids.get('city-district').dispatchEvent=()=>{};e.ids.get('sidebar-location').requestSubmit=()=>{};
 e.ids.get('sidebar-toggle').addEventListener('click',()=>e.workspace.classList.toggle('sidebar-collapsed'));
 e.ids.get('replay-intro').addEventListener('click',()=>replayed++);
 for(const key of ['setFilter','setFeatureState','setLayoutProperty'])e.map[key]=()=>{};
 e.window.radarIntent={text:'機械工廠',preference:'上下游群聚優先'};
 const opened=[];
 for(const [name,title] of [['campusMatching','校園人才媒合'],['headhunter','獵頭Agent'],['recruitment','刊登召募']])e.window[name]={deactivate(){},open(values){opened.push([title,values]);}};
 Object.assign(e.context,{innerWidth:1440,Event:class {constructor(type){this.type=type;}},
  setTimeout(fn){timers.push(fn);return timers.length;},clearTimeout(){},requestAnimationFrame(fn){timers.push(fn);return timers.length;}});
 vm.runInContext(source,e.context);
 const tick=async()=>{while(timers.length)timers.shift()();await flush();};
 const data=url=>{const result=JSON.parse(fs.readFileSync(path.join(__dirname,'../../ui/static',url.split('/').at(-1).split('?')[0]),'utf8'));return url.includes('district-stats.json')&&transformStats?transformStats(result):result;};
 const resolveAll=async()=>{for(const r of e.requests.filter(r=>!r.done)){r.done=true;r.resolve({ok:true,json:async()=>data(r.url)});}await flush();await tick();};
 return {...e,tick,resolveAll,replayed:()=>replayed,launched,opened};
}
test('ranking back returns to the original demand and unchanged intent preserves criteria',async()=>{
 const e=setup();const loading=e.window.siteScan.start();await e.resolveAll();await loading;await e.tick();
 const input=e.ids.get('scan-criteria').querySelector('input');input.checked=false;input.emit('change');
 assert.ok(e.ids.get('scan-back'),'ranking needs a visible previous step');
 e.ids.get('scan-back').click();assert.equal(e.replayed(),1);
 const again=e.window.siteScan.start();await again;await e.tick();
 assert.equal(e.ids.get('scan-criteria').querySelector('input').checked,false);
});
test('comparison and selected site can go backwards without clearing selected criteria',async()=>{
 const e=setup();const loading=e.window.siteScan.start();await e.resolveAll();await loading;await e.tick();
 e.ids.get('scan-compare').click();await e.resolveAll();await e.tick();
 assert.equal(e.workspace.classList.contains('scan-report'),true);
 e.ids.get('report-supply').querySelector('button').click();await e.tick();
 assert.equal(e.ids.get('hire-plan').hidden,false);
 assert.ok(e.ids.get('hire-plan-back'),'selected site needs a previous step');e.ids.get('hire-plan-back').click();await e.tick();
 assert.equal(e.ids.get('hire-plan').hidden,true);assert.equal(e.workspace.classList.contains('scan-report'),true);
 e.ids.get('scan-back').click();await e.tick();assert.equal(e.workspace.classList.contains('scan-report'),false);
});
test('back during a pending report request cannot reopen comparison afterwards',async()=>{
 const e=setup();const loading=e.window.siteScan.start();await e.resolveAll();await loading;await e.tick();
 e.ids.get('scan-compare').click();
 assert.ok(e.ids.get('scan-back'));e.ids.get('scan-back').click();
 await e.resolveAll();await e.tick();assert.equal(e.workspace.classList.contains('scan-report'),false);assert.equal(e.replayed(),1);
});

test('each hiring feature returns to the selected site plan without losing its title',async()=>{
 const e=setup();const loading=e.window.siteScan.start();await e.resolveAll();await loading;await e.tick();
 e.ids.get('scan-compare').click();await e.resolveAll();await e.tick();
 e.ids.get('report-supply').querySelector('button').click();await e.tick();
 const title=e.ids.get('hire-plan-title').textContent;
 for(const name of ['校園人才媒合','刊登召募','獵頭Agent']){
  const button=e.ids.get('hire-plan-list').querySelectorAll('button').find(b=>b.textContent.includes(name));button.click();await e.tick();
  assert.equal(e.opened.at(-1)[0],name);assert.equal(e.ids.get('scan-feature-back').hidden,false);
  e.ids.get('scan-feature-back').click();await e.tick();
  assert.equal(e.ids.get('hire-plan').hidden,false);assert.equal(e.ids.get('hire-plan-title').textContent,title);assert.equal(e.ids.get('scan-feature-back').hidden,true);
 }
});
test('back while initial ranking data loads prevents stale scan from covering demand',async()=>{
 const e=setup();const loading=e.window.siteScan.start();e.ids.get('scan-back').click();await e.resolveAll();await loading;await e.tick();
 assert.equal(e.workspace.classList.contains('scan-active'),false);assert.equal(e.replayed(),1);
});
test('editing the original demand resets criteria rather than reusing stale conditions',async()=>{
 const e=setup();const loading=e.window.siteScan.start();await e.resolveAll();await loading;await e.tick();
 const input=e.ids.get('scan-criteria').querySelector('input');input.checked=false;input.emit('change');
 e.ids.get('scan-back').click();e.window.radarIntent={text:'電子工廠',preference:''};await e.window.siteScan.start();await e.tick();
 assert.equal(e.ids.get('scan-criteria').querySelector('input').checked,true);assert.match(e.ids.get('scan-tags').textContent,/電子零組件/);
});
test('the site scan hands values to each feature through open() instead of its field ids',async()=>{
 const e=setup();const loading=e.window.siteScan.start();await e.resolveAll();await loading;await e.tick();
 e.ids.get('scan-compare').click();await e.resolveAll();await e.tick();
 e.ids.get('report-supply').querySelector('button').click();await e.tick();
 for(const name of ['校園人才媒合','刊登召募','獵頭Agent']){
  e.ids.get('hire-plan-list').querySelectorAll('button').find(b=>b.textContent.includes(name)).click();await e.tick();
  e.ids.get('scan-feature-back').click();await e.tick();
 }
 const values=Object.fromEntries(e.opened);
 assert.equal(values['校園人才媒合'].query,'機械');
 assert.match(values['刊登召募'].note,/^在.+區中清路三段設廠，想招/,'the drafted request names the picked district and road');
 assert.equal(values['獵頭Agent'].job,'機械工程師');
 assert.deepEqual(e.launched,[],'the feature buttons are no longer clicked to open a feature');
});
test('market vitality is a net entry rate and the cluster shows size with a location quotient',async()=>{
 const e=setup(completeEmployees);const loading=e.window.siteScan.start();await e.resolveAll();await loading;await e.tick();
 const podium=e.ids.get('scan-podium').querySelectorAll('small').map(small=>small.textContent).join('\n');
 assert.match(podium,/市場活力：淨增 [+-]?\d+\.\d%/,'vitality is (setups − dissolutions) ÷ companies, not a raw count');
 assert.match(podium,/同業群聚：[\d,]+ 人・LQ \d+\.\d\d/,'cluster names its employees and location quotient');
 assert.doesNotMatch(podium,/Infinity|NaN/);
});
test('transport only counts when the demand asks for it, and stability is an exit rate',async()=>{
 const plain=setup();let loading=plain.window.siteScan.start();await plain.resolveAll();await loading;await plain.tick();
 const labels=e=>e.ids.get('scan-criteria').querySelectorAll('input').map(input=>input.checked);
 const podium=e=>e.ids.get('scan-podium').querySelectorAll('small').map(small=>small.textContent).join('\n');
 assert.equal(labels(plain).filter(Boolean).length,4,'without a transport request the four original criteria stay as they were');
 assert.doesNotMatch(podium(plain),/交通便利/);
 assert.match(podium(plain),/經營穩定：退出率 \d+\.\d%/);
 const near=setup();near.window.radarIntent={text:'機械工廠',preference:'靠近交通樞紐'};
 loading=near.window.siteScan.start();await near.resolveAll();await loading;await near.tick();
 assert.equal(labels(near).filter(Boolean).length,5);
 assert.match(podium(near),/交通便利：最近交流道 \d+\.\d 公里/);
 assert.doesNotMatch(podium(near),/交通便利：無資料|Infinity|NaN/);
});
test('port, airport and high-speed rail have data and only count when the demand asks for them',async()=>{
 const e=setup();e.window.radarIntent={text:'機械工廠，要靠近港口方便出口',preference:''};
 const loading=e.window.siteScan.start();await e.resolveAll();await loading;await e.tick();
 const rows=e.ids.get('scan-criteria').querySelectorAll('input');
 assert.equal(rows.length,8,'four standing criteria plus transport, port, airport and high-speed rail');
 assert.equal(rows.filter(input=>input.checked).length,5,'only the port is added to the standing four');
 const podium=e.ids.get('scan-podium').querySelectorAll('small').map(small=>small.textContent).join('\n');
 assert.match(podium,/靠近港口：到臺中港 \d+\.\d 公里/);
 assert.doesNotMatch(podium,/靠近港口：無資料|靠近機場|靠近高鐵|NaN/);
 assert.equal(e.ids.get('scan-gap').textContent,'','港口 is no longer reported as missing data');
});

function completeEmployees(stats){
 const names=Object.keys(stats.factories.districts);
 stats.factories.districts=Object.fromEntries(names.map(name=>[name,{'機械設備業':['太平區','西屯區'].includes(name)?100:0,'其他':0}]));
 stats.factories.employees=Object.fromEntries(names.map(name=>[name,{'機械設備業':['太平區','西屯區'].includes(name)?100:0,'其他':['太平區','西屯區'].includes(name)?900:0}]));
 return stats;
}
const clusterText=e=>e.ids.get('scan-podium').querySelectorAll('small').map(s=>s.textContent).join('\n');
test('suppressed employee totals cannot produce an inflated location quotient',async()=>{
 const e=setup(stats=>{completeEmployees(stats);stats.factories.employees['太平區']['其他']=null;return stats;});
 const loading=e.window.siteScan.start();await e.resolveAll();await loading;await e.tick();
 assert.match(clusterText(e),/同業群聚：100 人・LQ 無資料/);
 assert.doesNotMatch(clusterText(e),/LQ 5\.50/);
});
test('unknown city industry employment invalidates location quotients in other districts too',async()=>{
 const e=setup(stats=>{completeEmployees(stats);stats.factories.employees['西屯區']['機械設備業']=null;return stats;});
 const loading=e.window.siteScan.start();await e.resolveAll();await loading;await e.tick();
 assert.match(clusterText(e),/同業群聚：100 人・LQ 無資料/);
 assert.doesNotMatch(clusterText(e),/LQ \d/);
});
test('complete totals retain a valid location quotient and exact zero observations',async()=>{
 const e=setup(completeEmployees);
 const loading=e.window.siteScan.start();await e.resolveAll();await loading;await e.tick();
 assert.match(clusterText(e),/同業群聚：100 人・LQ 1\.00/);
});
