const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const RecruitmentFlow=require('../../ui/static/recruitment-flow.js');
const {parseBrief,PostingBatch,PostingArchive}=RecruitmentFlow;

const formats=[
 ['4萬到6萬',40000,60000],['四萬到六萬',40000,60000],['4萬到六萬',40000,60000],
 ['4.5萬至6.5萬',45000,65000],['4.5到6萬',45000,60000],['4到6萬',40000,60000],
 ['40,000至60,000',40000,60000],['40000元至60000元',40000,60000],
 ['十萬元',100000,100000],['五萬五千至六萬元',55000,60000],['4萬5千到6萬',45000,60000],
 ['NT$ 50000',50000,50000],['TWD 50000',50000,50000],['５萬至６萬',50000,60000],
];
for(const [amount,low,high] of formats)test('salary amount: '+amount,()=>{
 const result=parseBrief('2位工程師，月薪'+amount);
 assert.deepEqual(result,[{role:'工程師',hires:2,salaryMin:low,salaryMax:high}]);
});

test('wan salary remains 40000..60000 through batch approval and archive',()=>{
 const jobs=parseBrief('2位工程師，月薪4萬到6萬');
 const batch=new PostingBatch(jobs.map(j=>({company:'測試企業',address:'台中',...j})));
 batch.flows.forEach(f=>f.complete());batch.publish([{}]);
 const record=new PostingArchive().add(batch.flows[0],'test');
 assert.deepEqual([record.draft.salaryMin,record.draft.salaryMax],[40000,60000]);
});

test('role-named salaries after all counts stay with their named jobs',()=>{
 for(const salaries of ['工程師月薪50000、經理月薪100000','經理月薪100000、工程師月薪50000']){
  const result=parseBrief('1位工程師、1位經理，'+salaries);
  assert.deepEqual(result.map(j=>[j.role,j.salaryMin,j.salaryMax]),[['工程師',50000,50000],['經理',100000,100000]]);
 }
});

test('an explicit salary does not leak into an unspecified job',()=>{
 const jobs=parseBrief('1位工程師、1位經理，工程師的月薪是5萬');
 assert.equal(jobs[0].salaryMin,50000);
 assert.equal(jobs[1].salaryMin,undefined);
 const batch=new PostingBatch(jobs.map(j=>({company:'測試企業',address:'台中',...j})));
 batch.flows.forEach(f=>f.complete());
 assert.throws(()=>batch.publish([{},{}]),/薪資|月薪/);
 assert.ok(batch.flows.every(f=>f.state==='preview'));
});

test('overlapping and punctuation-bearing job names are matched exactly',()=>{
 const jobs=parseBrief('1位前端工程師、1位工程師、1位C++工程師，工程師月薪5萬、前端工程師月薪6萬、C++工程師月薪7萬');
 assert.deepEqual(jobs.map(j=>j.salaryMin),[60000,50000,70000]);
});

test('unknown longer salary titles are rejected instead of matching a shorter known title',()=>{
 assert.throws(()=>parseBrief('1位工程師、1位經理，助理經理月薪40000'),/薪資|職缺/);
});

test('decimal wan amounts use exact yuan conversion',()=>{
 for(const [amount,expected] of [['4.56萬',45600],['2.53萬',25300],['4.5萬5千',50000]]){
  assert.equal(parseBrief('1位工程師月薪'+amount)[0].salaryMin,expected,amount);
 }
 assert.throws(()=>parseBrief('1位工程師月薪4.56元'),/月薪|正整數/);
});

test('fractional and signed headcounts fail closed before drafts can be created',()=>{
 for(const count of ['2.5','-2','+2']){
  assert.throws(()=>parseBrief(count+'位工程師，月薪50000'),/人數/);
 }
 const valid=parseBrief('2位工程師，月薪50000');
 assert.equal(valid[0].hires,2);
});

test('inline salaries and comma-separated next headcounts still parse',()=>{
 assert.deepEqual(parseBrief('3位工程師月薪50000至60000,5位助理月薪35,000').map(j=>[j.role,j.hires,j.salaryMin,j.salaryMax]),[['工程師',3,50000,60000],['助理',5,35000,35000]]);
 assert.equal(parseBrief('1,000位作業員')[0].hires,1000);
});

test('unknown, duplicate or conflicting salary owners are rejected without a partial result',()=>{
 for(const text of [
  '1位工程師，經理月薪100000',
  '1位工程師、2位工程師，工程師月薪5萬',
  '1位工程師月薪5萬，工程師月薪6萬',
  '1位工程師月薪5萬，另給薪資6萬',
 ])assert.throws(()=>parseBrief(text),/薪資|月薪|職缺/);
 assert.equal(parseBrief('1位工程師月薪5萬，工程師月薪5萬')[0].salaryMin,50000);
});

test('unsupported and malformed salaries fail closed instead of accepting a numeric prefix',()=>{
 for(const salary of ['4k','4,50','4萬到','4萬到6000','4.5元','0','60000至40000','五萬以上','5萬USD','5.5.5萬','5萬至未知']){
  assert.throws(()=>parseBrief('1位工程師月薪'+salary),/薪資|月薪/,salary);
 }
 assert.throws(()=>parseBrief('1位工程師年薪60萬'),/薪資|月薪/);
});

test('a rejected chat message preserves returned drafts and allows correction and resubmission',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../ui/static/recruitment.js'),'utf8');
 const nodes=new Map(),listeners=new Map(),messages=[];
 const $=id=>{
  if(!nodes.has(id))nodes.set(id,{value:'',addEventListener:(event,fn)=>listeners.set(id,fn),focus(){},requestSubmit(){this.submitted=true;}});
  return nodes.get(id);
 };
 const retained={brief:'原有草稿',index:0,jobs:[{role:'資深工程師',hires:3}]};
 const c={RecruitmentFlow,$,returnedDrafts:retained,pendingJobs:[],chatMessage:(kind,text)=>messages.push({kind,text})};
 vm.createContext(c);
 const start=source.indexOf('  function returnedJobs('),end=source.indexOf("  panel.querySelectorAll('[data-chat-action]')");
 vm.runInContext(source.slice(start,end),c);
 $('posting-brief').value='2位工程師，月薪4k';listeners.get('posting-parse')();
 assert.equal($('posting-form').submitted,undefined);
 assert.equal(c.pendingJobs.length,0);assert.equal(c.returnedDrafts,retained);
 assert.match(messages.at(-1).text,/薪資|月薪/);
 $('posting-brief').value='2位工程師，月薪4萬到6萬';listeners.get('posting-parse')();
 assert.equal($('posting-form').submitted,true);
 assert.equal(c.pendingJobs[0].salaryMin,40000);assert.equal(c.pendingJobs[0].salaryMax,60000);
 assert.equal(c.returnedDrafts,null);
});
