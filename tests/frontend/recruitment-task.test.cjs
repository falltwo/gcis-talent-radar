const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../../ui/static/recruitment-api.js'),'utf8');
function storage(){const data=new Map();return {getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};}
function load(sessionStorage,fetcher=async()=>new Response('{}')){
 const context={module:{exports:{}},sessionStorage,fetch:fetcher,crypto:globalThis.crypto,AbortController,Response,setTimeout,clearTimeout};
 vm.runInNewContext(source,context);return context.module.exports;
}
test('refresh restores same tab conversation; another tab and new intake stay separate',()=>{
 const data=storage(),API=load(data),first=new API(),id=first.conversationId;
 const refreshed=new (load(data))();assert.equal(refreshed.conversationId,id);
 assert.notEqual(new (load(storage()))().conversationId,id);
 refreshed.newConversation();assert.notEqual(new (load(data))().conversationId,id);
});
test('failed response retries same request even after refresh',async()=>{
 const data=storage(),calls=[];
 const failed=new (load(data,async(url,options)=>{calls.push(JSON.parse(options.body));throw new TypeError('lost response');}))();
 await assert.rejects(failed.assistant('招募一位工程師','太平區'));
 const restored=new (load(data,async(url,options)=>{calls.push(JSON.parse(options.body));return new Response('{"kind":"ack"}');}))();
 await restored.assistant('招募一位工程師','太平區');
 assert.match(calls[0].request_id,/^[A-Za-z0-9_-]{1,80}$/);
 assert.equal(calls[0].request_id,calls[1].request_id);
 assert.equal(calls[0].conversation_id,calls[1].conversation_id);
});
test('blocked session storage does not break sending or reset',async()=>{
 const blocked={getItem(){throw Error('blocked');},setItem(){throw Error('blocked');},removeItem(){throw Error('blocked');}};
 const api=new (load(blocked))();api.newConversation();await api.assistant('hello');
});

test('reopening shows recovered roles and conditions without starting the browser',async()=>{
 const elements=new Map(),calls=[];
 function element(){return {hidden:false,value:'',dataset:{},children:[],listeners:{},classList:{contains:()=>true,add(){},remove(){},toggle(){}},setAttribute(){},removeAttribute(){},addEventListener(k,f){this.listeners[k]=f;},append(...nodes){this.children.push(...nodes);},replaceChildren(){this.children=[];},querySelectorAll:()=>[],focus(){},click(){this.listeners.click?.();}};}
 const get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
 const task={batch_id:42,items:[{title:'現場技術人員',quantity:5,location:'太平區',salary_min:40000,salary_max:40000,salary_type:'monthly',description:'維修機台，協助生產'}]};
 class API{constructor(){this.token='demo';this.conversationId='same-tab';}async task(){return task;}}
 class Live{async start(){calls.push('start');}}
 const window={addEventListener(){},streetMap:{closeCompany(){}},radarFeatures:{select(){}}};
 vm.runInNewContext(fs.readFileSync(require.resolve('../../ui/static/recruitment.js'),'utf8'),{document:{getElementById:get,querySelector:()=>element(),createElement:element},window,RecruitmentAPI:API,RecruitmentLiveRun:Live,RecruitmentComposer:{bind(){}}});
 window.recruitment.toggle();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(get('posting-task').hidden,false);
 assert.match(get('posting-task-summary').textContent,/現場技術人員 5人/);
 assert.match(get('posting-chat-messages').children.at(-1).children.at(-1).textContent,/40000/);
 assert.equal(get('posting-publish').hidden,true);
 assert.equal(get('posting-run').hidden,true);
 assert.deepEqual(calls,[]);
});
