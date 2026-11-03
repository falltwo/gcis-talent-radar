/* Deterministic local demonstration. No browser automation or external publishing. */
(function(root){
  'use strict';
  const fields=['company','role','address','salary','hires','skills'];
  class PostingFlow{
    constructor(){this.cancel();}
    start(input){
      const draft={...input};
      for(const key of ['company','role','address','skills'])if(typeof draft[key]!=='string'||!draft[key].trim())throw Error('請填妥公司、職稱、地點與工作條件。');
      for(const key of ['salaryMin','salaryMax','hires'])draft[key]=Number(draft[key]);
      if(!Number.isFinite(draft.salaryMin)||!Number.isFinite(draft.salaryMax)||draft.salaryMin<=0||draft.salaryMax<draft.salaryMin)throw Error('請確認薪資為正數，且上限不低於下限。');
      if(!Number.isInteger(draft.hires)||draft.hires<1||draft.hires>100000)throw Error('招募人數須為 1 至 100000 的整數。');
      this.draft=Object.freeze(draft);this.index=0;this.state='filling';
    }
    advance(){if(this.state!=='filling')return null;const key=fields[this.index++];if(this.index===fields.length)this.state='preview';return key;}
    publish(confirmed){if(this.state!=='preview'||confirmed!==true)throw Error('請先完成預覽並由使用者確認。');this.state='published';return this.draft;}
    cancel(){this.state='idle';this.draft=null;this.index=0;}
  }
  function scenarioHires(text){const count=Number(String(text||'').replace(/,/g,'').replace(/\s*人\s*$/,'').trim());return Number.isInteger(count)&&count>=1&&count<=100000?count:2;}
  const api={PostingFlow,scenarioHires};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.RecruitmentFlow=api;
})(globalThis);
