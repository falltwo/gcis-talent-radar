const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const RecruitmentFlow=require('../../ui/static/recruitment-flow.js');
const source=fs.readFileSync(path.join(__dirname,'../../ui/static/recruitment.js'),'utf8');
const base=role=>({company:'測試企業',role,address:'台中',hires:3,salaryMin:40000,salaryMax:50000,skills:'原工作內容'});
function dom(){
 const nodes=new Map(),listeners=new Map();
 const $=id=>{if(!nodes.has(id))nodes.set(id,{hidden:false,textContent:'',value:'',open:false,addEventListener:(event,fn)=>listeners.set(id,fn),reportValidity:()=>true,querySelector:()=>({textContent:''}),focus(){},requestSubmit(){this.submitted=true;}});return nodes.get(id);};
 return {$,listeners};
}
test('all approved snapshots survive map dismissal or exit before animation finishes',()=>{
 const handler=source.slice(source.indexOf("  $('posting-publish').addEventListener"),source.indexOf('  function renderMapResult'));
 for(const action of ['map dismiss','exit']){
  const batch=new RecruitmentFlow.PostingBatch(['會計','工程師','品管'].map(base));batch.flows.forEach(f=>f.complete());
  const {$,listeners}=dom();
  const c={RecruitmentFlow,DEMO_URL:'http://localhost/demo',batch,batchEdits:[],batchIndex:0,flow:batch.flows[0],panel:{dataset:{act:'review'}},$,active:true,epoch:0,archive:new RecruitmentFlow.PostingArchive(),taskOrigin:'test',reduced:false,mapEffects:{finish(){}},reviewView:'all',saveBatchEdit(){},updateReviewFocus(){},readyReview(){},renderArchive(){},renderMapResult(){},renderBatchNav(){},log(){},setTimeout(fn){c.pending=fn;return 1;},stop(){c.epoch++;c.pending=null;},act(a){c.panel.dataset.act=a;}};
  vm.createContext(c);vm.runInContext(handler,c);listeners.get('posting-publish')();
  assert.equal(c.archive.all().length,3,action+' must not defer saving behind presentation timers');
  assert.equal(typeof c.pending,'function');
  // Both real reset paths first stop timers and cancel the flows.
  c.stop();batch.flows.forEach(f=>f.cancel());c.batch=null;
  assert.deepEqual(c.archive.all().map(r=>r.draft.role).sort(),['品管','工程師','會計'].sort());
  assert.equal(c.archive.countForOrigin('test'),3);
 }
});
function returnedFixture(roles,index=0){
 const batch=new RecruitmentFlow.PostingBatch(roles.map(base));batch.flows.forEach(f=>f.complete());
 const {$,listeners}=dom();
 const inputs=Object.fromEntries(Object.entries({...base('資深工程師'),hires:'5',salaryMin:'51000',salaryMax:'62000',skills:'人工修改技能'}).map(([k,value])=>[k,{value:String(value)}]));
 const c={RecruitmentFlow,$,batch,batchIndex:index,batchEdits:[],flow:batch.flows[index],inputs,pendingJobs:[],returnedDrafts:null,briefText:roles.map(r=>'3位'+r).join('、'),chatMessage(){},saveBatchEdit(){c.batchEdits[index]=Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value]));},reset(){c.batch.flows.forEach(f=>f.cancel());c.batch=null;c.pendingJobs=[];c.batchEdits=[];c.returnedDrafts=null;},reviewCarry:null};
 $('posting-brief').value=c.briefText;
 const helperStart=source.indexOf('  function returnedJobs(');
 const parseStart=helperStart<0?source.indexOf("  $('posting-parse').addEventListener"):helperStart;
 const parse=source.slice(parseStart,source.indexOf("  panel.querySelectorAll('[data-chat-action]')"));
 const back=source.slice(source.indexOf('  function back(){'),source.indexOf("  $('posting-edit').addEventListener"));
 vm.createContext(c);vm.runInContext(parse+back,c);vm.runInContext('back()',c);
 return {c,$,send:()=>listeners.get('posting-parse')()};
}
test('resending unchanged chat after return retains edited title/count instead of reparsing old message',()=>{
 const {c,$,send}=returnedFixture(['工程師']);send();
 assert.equal($('posting-form').submitted,true);
 assert.equal(c.pendingJobs[0].role,'資深工程師');assert.equal(Number(c.pendingJobs[0].hires),5);
 assert.equal(Number(c.pendingJobs[0].salaryMin),51000);assert.equal(c.pendingJobs[0].skills,'人工修改技能');
});
test('returning one selected job preserves other jobs and permits further edits in details',()=>{
 const {c,$,send}=returnedFixture(['會計','工程師'],1);
 $('posting-role').value='主任工程師';$('posting-hires').value='7';send();
 assert.equal(c.pendingJobs.length,2);assert.equal(c.pendingJobs[0].role,'會計');
 assert.equal(Number(c.pendingJobs[0].salaryMin),40000);assert.equal(c.pendingJobs[0].skills,'原工作內容');
 assert.equal(c.pendingJobs[1].role,'主任工程師');assert.equal(Number(c.pendingJobs[1].hires),7);
 assert.equal(Number(c.pendingJobs[1].salaryMin),51000);
});
test('an explicitly changed chat message starts a new batch rather than reusing returned drafts',()=>{
 const {c,$,send}=returnedFixture(['工程師']);$('posting-brief').value='2位會計';send();
 assert.equal(c.pendingJobs.length,1);assert.equal(c.pendingJobs[0].role,'會計');assert.equal(c.pendingJobs[0].hires,2);
 assert.equal(c.returnedDrafts,null);
});
test('retrying returned details after failed browser validation uses the latest corrections',()=>{
 const {c,$,send}=returnedFixture(['工程師']);
 $('posting-company').value='';send();
 // requestSubmit() cannot dispatch submit while the required company is empty.
 assert.equal(c.pendingJobs[0].company,'');
 $('posting-company').value='已修正企業';
 let submit;
 $('posting-form').addEventListener=(event,fn)=>{submit=fn;};
 c.FormData=class{constructor(){return new Map(['company','role','address','hires'].map(key=>[key,$('posting-'+key).value]).concat([['skills',$('posting-known').value]]));}};
 // Exercise the actual submit listener's construction/validation before animations start.
 const start=source.indexOf("  $('posting-form').addEventListener('submit'");
 const animation=source.indexOf("    stop();act('working')",start);
 vm.runInContext(source.slice(start,animation)+'  });',c);
 submit({preventDefault(){},currentTarget:$('posting-form')});
 assert.equal($('posting-error').textContent,'');
 assert.equal(c.batch.flows[0].draft.company,'已修正企業');
 assert.equal(c.batch.flows[0].draft.role,'資深工程師');
 assert.equal(c.returnedDrafts,null);
});
