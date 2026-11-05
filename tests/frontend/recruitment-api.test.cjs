const {test}=require('node:test');
const assert=require('node:assert/strict');
const API=require('../../ui/static/recruitment-api.js');

test('login token is sent to same-origin batch endpoint with original Chinese demand',async()=>{
  const calls=[];
  const api=new API(async(url,options)=>{calls.push([url,options]);return new Response(JSON.stringify(url.endsWith('/login')?{access_token:'test-token'}:{id:7,items:[]}));});
  await assert.rejects(api.createBatch('十位軟體工程師'),/連接/);
  await api.login('hr@example.com','test-password');
  await api.createBatch('十位軟體工程師，十位硬體工程師');
  assert.equal(calls[1][0],'/api/recruitment/mvp/batches');
  assert.equal(calls[1][1].headers.Authorization,'Bearer test-token');
  assert.deepEqual(JSON.parse(calls[1][1].body),{message:'十位軟體工程師，十位硬體工程師'});
});

test('backend fields map to demo fields without inventing salary or changing amount',()=>{
  const jobs=API.jobs({items:[{id:1,title:'軟體工程師',quantity:10,location:'大雅區',description:'開發系統',requirements:'JavaScript',salary_type:'monthly',currency:'TWD',salary_min:40000,salary_max:60000},{id:2,title:'硬體工程師',quantity:10,salary_type:'monthly',currency:'TWD'}]});
  assert.deepEqual(jobs[0],{backendItemId:1,role:'軟體工程師',hires:10,address:'大雅區',skills:'開發系統',requirements:'JavaScript',salaryMin:40000,salaryMax:60000});
  assert.equal(jobs[1].salaryMin,null);
  assert.equal(jobs[1].salaryMax,null);
  assert.equal(jobs[1].skills,undefined);
});

test('hourly and yearly salary cannot become monthly salary',()=>{
  for(const type of ['hourly','yearly'])assert.throws(()=>API.jobs({id:3,items:[{salary_type:type,currency:'TWD'}]}),/不能將時薪或年薪/);
});

test('expired login clears token and validation failure retains backend explanation',async()=>{
  const api=new API(async()=>new Response('{}',{status:401}));api.token='expired';
  await assert.rejects(api.createBatch('十位工程師'),/重新連線/);assert.equal(api.token,null);
  api.fetcher=async()=>new Response(JSON.stringify({detail:'薪資歸屬不明確'}),{status:422});api.token='valid';
  await assert.rejects(api.createBatch('需求'),/薪資歸屬不明確/);
  assert.equal(api.token,'valid');
});

test('logout clears token even when server is unavailable',async()=>{
  const api=new API(async()=>{throw new TypeError('offline');});api.token='test';
  await assert.rejects(api.logout(),/無法連線/);assert.equal(api.token,null);
});

test('lost publish response recovers the committed records without publishing again',async()=>{
  let published=false,attempts=0;
  const item={id:11,title:'工程師',quantity:2};
  const api=new API(async(url,options)=>{
    if(url.endsWith('/publish')){attempts++;published=true;throw new TypeError('lost response');}
    const body=url.endsWith('/job-postings')?[{id:31,batch_item_id:11},{id:32,batch_item_id:99}]:{id:1,status:published?'published':'draft',items:[item]};
    return new Response(JSON.stringify(body));
  });
  api.token='test';
  const drafts=[{backendItemId:11,role:'工程師',hires:2,skills:'工程工作',requirements:'相關經驗',address:'台中',salaryMin:40000,salaryMax:50000}];
  assert.deepEqual((await api.publishBatch(1,drafts)).map(p=>p.id),[31]);
  assert.deepEqual((await api.publishBatch(1,drafts)).map(p=>p.id),[31]);
  assert.equal(attempts,1);
});

test('Computer Use handoff preserves the selected job and leaves unknown schedule blank',()=>{
  const batch={items:[{id:3,title:'前端工程師',quantity:10,description:'開發網頁介面',requirements:'JavaScript\nCSS',location:'大雅區',salary_type:'monthly',currency:'TWD',salary_min:40000,salary_max:60000}]};
  const job=API.portalJob(batch,3,'示範公司');
  assert.equal(job.title,'前端工程師');assert.equal(job.headcount,10);
  assert.deepEqual(job.required_skills,['JavaScript','CSS']);
  assert.equal(job.salary_min,40000);assert.equal(job.salary_max,60000);
  for(const field of ['shift','work_hours','schedule_system','employment_type'])assert.equal(job[field],'');
  assert.throws(()=>API.portalJob(batch,99,'示範公司'),/找不到/);
});
