// Run only against a disposable local database with RECRUITMENT_TEST_ORIGIN set.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const API=require('../../ui/static/recruitment-api.js');
const origin=process.env.RECRUITMENT_TEST_ORIGIN;
test('real API: Chinese intake → save → reopen → confirm → publish → retry → relogin',{skip:!origin},async()=>{
  const api=new API((url,options)=>fetch(origin+url,options));
  const email=`integration-${Date.now()}@example.invalid`,password='integration-test-only-123';
  await api.register({company_name:'串接測試公司',name:'測試HR',email,password});
  await api.login(email,password);
  assert.equal((await api.request('/auth/me')).company_name,'串接測試公司');
  const batch=await api.createBatch('十位軟體工程師，十位硬體工程師');
  assert.deepEqual(batch.items.map(i=>[i.title,i.quantity]),[['軟體工程師',10],['硬體工程師',10]]);
  const drafts=API.jobs(batch).map(j=>({...j,address:'臺中市大雅區',skills:'測試工作內容',requirements:'相關專業知識',salaryMin:40000,salaryMax:60000}));
  drafts[1].role='硬體研發工程師';
  await api.saveBatch(batch.id,drafts);
  const reopened=await api.request('/batches/'+batch.id);
  assert.equal(reopened.items[1].title,'硬體研發工程師');
  assert.equal(reopened.items[1].requirements,'相關專業知識');
  // Invalid later item must be rejected before any edits are sent.
  await assert.rejects(api.publishBatch(batch.id,[{...drafts[0],role:'不應寫入'}, {...drafts[1],requirements:''}]),/任職條件/);
  assert.equal((await api.request('/batches/'+batch.id)).items[0].title,'軟體工程師');
  const postings=await api.publishBatch(batch.id,drafts);
  assert.equal(postings.length,2);
  assert.equal((await api.request('/batches/'+batch.id)).status,'published');
  assert.deepEqual((await api.publishBatch(batch.id,drafts)).map(p=>p.id),postings.map(p=>p.id));
  await api.logout();await api.login(email,password);
  assert.equal((await api.request('/job-postings')).length,2);
  const other=new API((url,options)=>fetch(origin+url,options));
  await other.register({company_name:'其他公司',name:'其他HR',email:'other-'+email,password});
  await other.login('other-'+email,password);
  assert.equal((await other.request('/job-postings')).length,0);
  await assert.rejects(other.request('/batches/'+batch.id),/找不到批次/);
  await other.logout();await api.logout();
});
