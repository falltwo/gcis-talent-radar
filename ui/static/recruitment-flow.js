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
  const salaryDigits={零:0,〇:0,一:1,二:2,兩:2,三:3,四:4,五:5,六:6,七:7,八:8,九:9};
  const salaryUnits={十:10,百:100,千:1000,萬:10000,万:10000};
  const salaryAmount=String.raw`(?:\d+(?:,\d{3})*(?:\.\d+)?|[零〇一二兩三四五六七八九十百千萬万]+)(?:[萬万千百十](?:\d+(?:\.\d+)?|[零〇一二兩三四五六七八九十百千萬万]+)?)*`;
  const salaryExpression=new RegExp(String.raw`^(?:月薪|薪資)\s*(?:為|是|[:：])?\s*(?:NT\$|TWD|新台幣)?\s*(${salaryAmount})\s*元?(?:\s*(?:至|到|[-~～–])\s*(${salaryAmount})\s*元?)?`,'i');
  function salaryNumber(text){
    for(const part of text.match(/\d[\d,]*/g)||[])if(part.includes(',')&&!/^\d{1,3}(?:,\d{3})+$/.test(part))throw Error('薪資千分位格式不正確，請重新確認。');
    const raw=text.replace(/,/g,'');
    if(/^\d+(?:\.\d+)?$/.test(raw))return Number(raw);
    if(/^[零〇一二兩三四五六七八九]+$/.test(raw))return Number([...raw].map(c=>salaryDigits[c]).join(''));
    const tokens=raw.match(/\d+(?:\.\d+)?|[零〇一二兩三四五六七八九十百千萬万]/g)||[];
    if(tokens.join('')!==raw)throw Error('無法辨識薪資金額，請重新確認。');
    let total=0,section=0,pending=null,lastUnit=10000,wan=false;
    for(const token of tokens){
      const unit=salaryUnits[token];
      if(!unit){
        if(pending!==null&&pending!==0)throw Error('薪資數字格式不明確，請重新確認。');
        pending=token in salaryDigits?salaryDigits[token]:Number(token);
      }else if(unit===10000){
        if(wan)throw Error('薪資萬位格式不明確，請重新確認。');
        total+=(section+(pending??0)||1)*unit;section=0;pending=null;lastUnit=10000;wan=true;
      }else{
        if(unit>=lastUnit)throw Error('薪資單位順序不正確，請重新確認。');
        section+=(pending??1)*unit;pending=null;lastUnit=unit;
      }
    }
    return total+section+(pending??0);
  }
  function assignSalaries(clean,spans){
    for(const mention of clean.matchAll(/月薪|薪資|年薪|時薪|薪水|待遇/g)){
      const match=clean.slice(mention.index).match(salaryExpression);
      if(!match)throw Error('請明確指定月薪，例如「工程師月薪4萬到6萬」；無法辨識的薪資不會自動帶入。');
      const tail=clean.slice(mention.index+match[0].length).trimStart();
      // A partial numeric match must never turn an unsupported amount into a valid salary.
      if(/^[\d零〇一二兩三四五六七八九十百千萬万.至到~～–-]|^(?:以上|以下|起|左右|美金|美元|USD|[a-z])/i.test(tail)||(/^,\s*\d/.test(tail)&&!/^,\s*\d[\d,]*\s*[位名個人]/.test(tail)))throw Error('薪資範圍或單位無法完整辨識，請重新確認。');
      const prefix=clean.slice(0,mention.index).trimEnd();
      const named=spans.filter(s=>{
        const escaped=s.job.role.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
        return new RegExp(escaped+String.raw`\s*(?:的\s*)?(?:[:：]\s*)?$`).test(prefix);
      }).sort((a,b)=>b.job.role.length-a.job.role.length);
      let owner;
      if(named.length){
        const longest=named[0].job.role;
        if(named.filter(s=>s.job.role===longest).length>1)throw Error('同名職缺的薪資歸屬不明確，請使用不同職稱。');
        owner=named[0];
      }else{
        // Bare salary clauses attach to the immediately preceding count/title only.
        // Any other named/prose prefix must be clarified rather than assigned to that job.
        const clause=prefix.split(/[、，,；;。\n]/).at(-1).trim();
        if(clause)throw Error('薪資無法對應職缺，請使用「職稱月薪金額」明確指定。');
        owner=spans.filter(s=>s.start<mention.index).at(-1);
      }
      if(!owner)throw Error('請先提供職稱與人數，再指定該職缺月薪。');
      let low=salaryNumber(match[1]),high=salaryNumber(match[2]||match[1]);
      if(match[2]){
        if(!/[十百千萬万]/.test(match[1])&&/[萬万]$/.test(match[2])&&low<10000)low*=10000;
      }
      if(!Number.isSafeInteger(low)||!Number.isSafeInteger(high)||low<=0||high<low)throw Error('請確認月薪上下限為正整數，且上限不低於下限。');
      const job=owner.job;
      if(job.salaryMin!==undefined&&(job.salaryMin!==low||job.salaryMax!==high))throw Error(`${job.role}有不同的薪資指定，請先釐清後再建立草稿。`);
      job.salaryMin=low;job.salaryMax=high;
    }
  }
  function parseBrief(text){
    const clean=String(text||'').normalize('NFKC'),jobs=[],spans=[];
    // Locate each count/title independently; a later count always starts another job.
    const starts=[...clean.matchAll(/(\d+(?:,\d{3})*)\s*[位名個人]\s*/g)];
    for(let i=0;i<starts.length;i++){
      const m=starts[i],count=Number(m[1].replace(/,/g,''));
      if(!Number.isInteger(count)||count<1||count>100000)continue;
      const segment=clean.slice(m.index+m[0].length,starts[i+1]?.index??clean.length);
      const role=segment.split(/[、，,；;。\n]|月薪|薪資|待遇|在|於|需要|希望/)[0].replace(/[及與和\s]+$/,'').trim();
      if(!role||role.length>80)continue;
      const job={role,hires:count};jobs.push(job);spans.push({start:m.index,job});
    }
    if(jobs.length)assignSalaries(clean,spans);
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
