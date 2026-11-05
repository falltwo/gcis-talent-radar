const {test}=require('node:test');
const assert=require('node:assert/strict');
const Live=require('../../ui/static/recruitment-live.js');
const base=role=>({company:'測試企業',role,address:'大雅區',hires:3,salaryMin:40000,salaryMax:50000,skills:'負責職務相關作業與品質確認。',requirements:'相關技能',employmentType:'全職',scheduleSystem:'固定班制',shift:'日班',workHours:'08:00–17:00',experienceYears:0});

test('all roles must have complete conditions before browser launch',()=>{
 const jobs=[base('前端工程師'),{...base('全端工程師'),workHours:''}];
 assert.throws(()=>Live.prepare(jobs),error=>error.jobIndex===1&&/上班時間/.test(error.message));
 jobs[1].workHours='09:00–18:00';
 assert.deepEqual(Live.prepare(jobs).map(j=>[j.title,j.headcount,j.salary_min]),[['前端工程師',3,40000],['全端工程師',3,40000]]);
});

test('partial numeric salary and fractional headcount fail before browser launch',()=>{
 for(const patch of [{salaryMin:'4k'},{salaryMax:30000},{hires:2.5},{salaryMin:''},{experienceYears:.01}])assert.throws(()=>Live.prepare([{...base('工程師'),...patch}]));
});

test('each real frame is forwarded and two jobs run sequentially without navigation',async()=>{
 const events=[],calls=[];let count=0,polls=0,cancelled=false;
 const request=async(path,body)=>{
  calls.push([path,body]);
  if(path==='agent/approve'){count++;polls=0;cancelled=false;assert.equal(body.fill_only,true);assert.equal(body.confirm_before_publish,true);return {run_id:'run-'+count};}
  if(path==='agent/cancel'){cancelled=true;return {};}
  if(path==='agent/run'){
   if(cancelled)return {browser_active:false};
   polls++;return {run_id:'run-'+count,phase:polls===1?'COMPUTER_RUNNING':'FILLED',driver:'COMPUTER_USE',job_id:'job-'+count,screenshot:'frame-'+count+'-'+polls};
  }
  return {};
 };
 const live=new Live(request,e=>events.push(e),async()=>{});
 const results=await live.start(Live.prepare([base('前端工程師'),base('全端工程師')]));
 assert.equal(results.length,2);
 assert.deepEqual(events.filter(e=>e.run).map(e=>e.run.screenshot),['frame-1-1','frame-1-2','frame-2-1','frame-2-2']);
 assert.equal(events.at(-1).phase,'COMPLETE');
 const cancelIndex=calls.findIndex(c=>c[0]==='agent/cancel');
 const secondApprove=calls.findIndex((c,i)=>i>cancelIndex&&c[0]==='agent/approve');
 assert.ok(cancelIndex>0&&secondApprove>cancelIndex);
 assert.ok(!calls.some(([p])=>/submit|publish|resume|batches/.test(p)));
});

test('a failed browser cannot become a completed publication candidate',async()=>{
 const events=[];const live=new Live(async(path)=>path==='agent/approve'?{run_id:'one'}:path==='agent/run'?{run_id:'one',phase:'FAILED',message:'模型失敗'}:{},e=>events.push(e),async()=>{});
 await assert.rejects(live.start([{}]),/模型失敗/);
 assert.equal(events.at(-1).phase,'FAILED');assert.equal(live.results.length,0);
});

test('missing screenshot or verifier job id cannot be reported as filled',async()=>{
 const live=new Live(async(path)=>path==='agent/approve'?{run_id:'one'}:path==='agent/run'?{run_id:'one',phase:'FILLED',driver:'COMPUTER_USE'}:{},()=>{},async()=>{});
 await assert.rejects(live.start([{}]),/完成證據/);
});

test('second job failure keeps only the first completed form',async()=>{
 let count=0;const live=new Live(async path=>{
  if(path==='agent/approve')return {run_id:'run-'+(++count)};
  if(path==='agent/run')return count===1?{run_id:'run-1',phase:'FILLED',driver:'COMPUTER_USE',job_id:'frontend-only',screenshot:'frame'}:{run_id:'run-2',phase:'FAILED',message:'已達操作上限',browser_active:false};
  return {};
 },()=>{},async()=>{});
 await assert.rejects(live.start([{},{}]),/操作上限/);
 assert.equal(live.results.length,1);assert.equal(live.results[0].job_id,'frontend-only');
});

test('two jobs cannot share the same review form id',async()=>{
 let count=0;const live=new Live(async path=>{
  if(path==='agent/approve')return {run_id:'run-'+(++count)};
  if(path==='agent/run')return {run_id:'run-'+count,phase:'FILLED',driver:'COMPUTER_USE',job_id:'same-form',screenshot:'frame',browser_active:false};
  return {};
 },()=>{},async()=>{});
 await assert.rejects(live.start([{},{}]),/同一份表格/);
 assert.equal(live.results.length,1);
});

test('stopping during a run cancels that run without starting the next job',async()=>{
 let approved=0;const live=new Live(async(path)=>{
  if(path==='agent/approve'){approved++;return {run_id:'one'};}
  if(path==='agent/run')return {run_id:'one',phase:'COMPUTER_RUNNING',browser_active:false};
  return {};
 },()=>{},async()=>{await live.stop();});
 await live.start([{},{}]);assert.equal(approved,1);assert.equal(live.results.length,0);
});

test('HR confirmation publishes the real filled PR22 form and retries skip completed items',async()=>{
 const calls=[],job={title:'會計',headcount:2};let status='DRAFT';
 const request=async(path)=>{calls.push(path);if(path.endsWith('/submit'))status='PENDING_APPROVAL';if(path.endsWith('/approve'))status='PROCESSING';if(path.endsWith('/complete'))status='SUCCEEDED';return {jobs:[{id:'real-job',data:job,status}]};};
 const results=[{phase:'FILLED',driver:'COMPUTER_USE',job_id:'real-job',screenshot:'real-frame',job}];
 await Live.publishFilled(results,request);await Live.publishFilled(results,request);
 assert.deepEqual(calls,['state','jobs/real-job/submit','jobs/real-job/approve','jobs/real-job/complete','state']);
 await assert.rejects(Live.publishFilled([{...results[0],job:{title:'不同職缺'}}],request),/內容不同/);
 await assert.rejects(Live.publishFilled([],request),/完成實際填表/);
});

test('manual review submits the edited revision without AI or automatic approval',async()=>{
 const job={title:'人工調整職稱',headcount:4};let status='DRAFT';const calls=[];
 const request=async(path,body)=>{calls.push([path,body]);if(path.endsWith('/submit')){assert.equal(body.expected_revision,2);status='PENDING_APPROVAL';}return {jobs:[{id:'manual-job',revision:2,data:job,status}]};};
 const result={phase:'REVIEW_REQUIRED',driver:'COMPUTER_USE',job_id:'manual-job',screenshot:'real-frame',job,human_reviewed:true,reviewed_revision:2};
 await Live.submitReviewed([result],request);await Live.submitReviewed([result],request);
 assert.equal(status,'PENDING_APPROVAL');assert.equal(calls.filter(([p])=>p.endsWith('/submit')).length,1);
 assert.ok(!calls.some(([p])=>/agent|approve|complete/.test(p)));
 await assert.rejects(Live.submitReviewed([{...result,human_reviewed:false}],request),/逐筆檢查/);
 await assert.rejects(Live.submitReviewed([{...result,reviewed_revision:1}],request),/已變更/);
});

test('first saved mismatched job completes into human review instead of restarting AI',async()=>{
 const live=new Live(async path=>path==='agent/approve'?{run_id:'one'}:path==='agent/run'?{run_id:'one',phase:'REVIEW_REQUIRED',driver:'COMPUTER_USE',job_id:'saved',screenshot:'actual',mismatches:{title:{}}}:{},()=>{},async()=>{});
 const results=await live.start([{}]);assert.equal(results[0].phase,'REVIEW_REQUIRED');assert.equal(results.length,1);
});
