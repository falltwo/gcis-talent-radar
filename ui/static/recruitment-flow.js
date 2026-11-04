/* Frontend demonstration state. No model, search or third-party publishing. */
(function(root){
  'use strict';
  const fields=['company','role','address','salary','hires','skills'];
  function normalized(input){
    const d={...input};
    for(const key of ['company','role','address','skills'])if(typeof d[key]!=='string'||!d[key].trim())throw Error('請填妥公司、職稱、地點與工作內容。');
    d.hires=Number(d.hires);if(!Number.isInteger(d.hires)||d.hires<1||d.hires>100000)throw Error('招募人數須為 1 至 100000 的整數。');
    for(const key of ['salaryMin','salaryMax'])d[key]=d[key]==null||d[key]===''?null:Number(d[key]);
    if(d.salaryMin!==null||d.salaryMax!==null){if(!Number.isFinite(d.salaryMin)||!Number.isFinite(d.salaryMax)||d.salaryMin<=0||d.salaryMax<d.salaryMin)throw Error('請完整填寫月薪上下限，且上限不低於下限。');}
    return Object.freeze(d);
  }
  class PostingFlow{
    constructor(){this.cancel();}
    start(input){
      const skills=input.skills?.trim()||`負責${input.role||'此職務'}相關作業，依企業標準執行工作、記錄進度與協助品質確認。詳細內容請由企業審核調整。`;
      const d=normalized({...input,skills});
      this.draft=d;this.index=0;this.state='filling';
      this.sources={company:'company',role:'user',address:'company',hires:'user',skills:input.skills?.trim()?'user':'template',salary:d.salaryMin===null?'pending':'user'};
    }
    advance(){if(this.state!=='filling')return null;const key=fields[this.index++];if(this.index===fields.length)this.state='preview';return key;}
    complete(){if(!['paused','filling'].includes(this.state))return;this.index=fields.length;this.state='preview';}
    pause(){if(['filling','preview'].includes(this.state))this.state='paused';}
    resume(){if(this.state==='paused')this.state='filling';}
    revise(patch){
      if(this.state!=='preview')throw Error('請在人工審核階段修改。');
      const next=normalized({...this.draft,...patch}),sources={...this.sources};
      for(const key of Object.keys(patch))if(next[key]!==this.draft[key])sources[key.startsWith('salary')?'salary':key]='human';
      if(next.salaryMin===null)sources.salary='pending';
      this.draft=next;this.sources=sources;
    }
    missing(){return this.draft&&this.draft.salaryMin===null?['salary']:[];}
    publish(confirmed){if(this.state!=='preview'||confirmed!==true)throw Error('請先完成審核並由使用者確認。');if(this.missing().length)throw Error('請先補充企業實際提供的月薪範圍。');this.state='published';return this.draft;}
    cancel(){this.state='idle';this.draft=null;this.sources={};this.index=0;}
  }
  function scenarioHires(text){const count=Number(String(text||'').replace(/,/g,'').replace(/\s*人\s*$/,'').trim());return Number.isInteger(count)&&count>=1&&count<=100000?count:2;}
  function needsReview(source,valid){return !valid||source==='pending'||source==='template';}
  class DemoNavigation{
    constructor(){this.reset();}
    reset(){this.state='blank';this.address='';this.target='';}
    begin(url,origin){const u=new URL(url);if(!['http:','https:'].includes(u.protocol)||u.origin!==origin)throw Error('僅能開啟目前網站的本機模擬頁。');this.target=u.href;this.address='';this.state='typing';}
    typeNext(){if(this.state!=='typing')return this.address;this.address=this.target.slice(0,this.address.length+3);if(this.address===this.target)this.state='entered';return this.address;}
    open(){if(this.state!=='entered')throw Error('網址尚未輸入完成。');this.state='loading';}
    ready(){if(this.state!=='loading')throw Error('模擬頁尚未開啟。');this.state='ready';}
    get canFill(){return this.state==='ready';}
  }
  class PostingArchive{
    constructor(){this.records=[];this.byDraft=new WeakMap();this.serial=0;}
    add(flow,origin){
      if(flow.state!=='published'||!flow.draft)throw Error('只有已完成審核刊登的職缺可加入紀錄。');
      if(this.byDraft.has(flow.draft))return this.byDraft.get(flow.draft);
      const record=Object.freeze({id:`posting-${++this.serial}`,origin:origin||null,createdAt:new Date().toISOString(),draft:Object.freeze({...flow.draft})});
      this.records.unshift(record);this.byDraft.set(flow.draft,record);return record;
    }
    all(){return [...this.records];}
    countForOrigin(origin){return this.records.filter(record=>record.origin===origin).length;}
    get(id){return this.records.find(record=>record.id===id)||null;}
  }
  function parseBrief(text){
    const clean=String(text||'').normalize('NFKC'),jobs=[];
    // Locate each count/title independently; a later count always starts another job.
    const starts=[...clean.matchAll(/(\d[\d,]*)\s*[位名個人]\s*/g)];
    for(let i=0;i<starts.length;i++){
      const m=starts[i],count=Number(m[1].replace(/,/g,''));
      if(!Number.isInteger(count)||count<1||count>100000)continue;
      const segment=clean.slice(m.index+m[0].length,starts[i+1]?.index??clean.length);
      const role=segment.split(/[、，,；;。\n]|月薪|薪資|待遇|在|於|需要|希望/)[0].replace(/[及與和\s]+$/,'').trim();
      if(!role||role.length>80)continue;
      const job={role,hires:count},salary=segment.match(/(?:月薪|薪資)\s*(?:NT\$|新台幣)?\s*(\d[\d,]*)(?:\s*(?:至|到|[-~～–])\s*(\d[\d,]*))?/i);
      if(salary){job.salaryMin=Number(salary[1].replace(/,/g,''));job.salaryMax=Number((salary[2]||salary[1]).replace(/,/g,''));}
      jobs.push(job);
    }
    return jobs;
  }
  class PostingBatch{
    constructor(drafts){
      if(!drafts.length||drafts.length>20)throw Error('每次請提供 1 至 20 筆職缺。');
      this.flows=drafts.map(d=>{const f=new PostingFlow();f.start(d);return f;});
    }
    publish(patches){
      if(patches.length!==this.flows.length||this.flows.some(f=>f.state!=='preview'))throw Error('請先完成所有職缺草稿。');
      const checked=this.flows.map((f,i)=>normalized({...f.draft,...patches[i]}));
      if(checked.some(d=>d.salaryMin===null))throw Error('請先補齊每筆職缺的月薪範圍。');
      this.flows.forEach((f,i)=>f.revise(patches[i]));
      return this.flows.map(f=>f.publish(true));
    }
  }
  const api={PostingFlow,scenarioHires,needsReview,DemoNavigation,PostingArchive,parseBrief,PostingBatch};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.RecruitmentFlow=api;
})(globalThis);
