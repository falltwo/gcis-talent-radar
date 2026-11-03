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
  const api={PostingFlow,scenarioHires,needsReview,DemoNavigation};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.RecruitmentFlow=api;
})(globalThis);
