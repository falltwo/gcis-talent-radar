/* Same-origin authenticated draft API. Credentials stay in memory. */
(function(root){
  'use strict';
  class RecruitmentAPI{
    constructor(fetcher=globalThis.fetch.bind(globalThis)){this.fetcher=fetcher;this.token=null;}
    async request(path,body,method){
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),['/assistant','/execution/prepare'].includes(path)?120000:30000);
      try{
        const response=await this.fetcher('/api/recruitment/mvp'+path,{
          method:method||(body===undefined?'GET':'POST'),signal:controller.signal,credentials:'same-origin',
          headers:{'Content-Type':'application/json',...(this.token?{Authorization:'Bearer '+this.token}:{})},
          ...(body===undefined?{}:{body:JSON.stringify(body)})
        });
        const data=await response.json().catch(()=>({}));
        if(!response.ok){
          if(response.status===401||response.status===403){this.token=null;throw Error('工作階段已失效或沒有權限，請重新連線。');}
          const detail=data.detail;
          throw Error(typeof detail==='string'?detail:Array.isArray(detail)?detail.map(e=>e.msg).join('；'):'服務暫時無法完成要求，請稍後重試。');
        }
        return data;
      }catch(error){
        if(error.name==='AbortError')throw Error('等待服務逾時。變更可能已儲存，請先查詢招募資料與刊登紀錄，再決定是否重試。');
        if(error instanceof TypeError)throw Error('無法連線。變更可能已儲存，請恢復連線後先查詢招募資料與刊登紀錄。');
        throw error;
      }finally{clearTimeout(timer);}
    }
    async login(email,password){const data=await this.request('/auth/login',{email,password});this.token=data.access_token;return data;}
    async startDemo(){const data=await this.request('/auth/demo',{});this.token=data.access_token;return data;}
    register(data){return this.request('/auth/register',data);}
    async logout(){try{if(this.token)await this.request('/auth/logout',{});}finally{this.token=null;}}
    async assistant(message,district=''){return this.request('/assistant',{message,district});}
    async portal(path,body){
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
      try{
        const response=await this.fetcher('/api/mock104/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',signal:controller.signal,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
        const data=await response.json().catch(()=>({}));
        if(!response.ok){const error=Error(typeof data.detail==='string'?data.detail:'填表服務未能完成要求，請確認條件後重試。');error.status=response.status;throw error;}
        return data;
      }catch(error){if(error.name==='AbortError')throw Error('填表服務連線逾時，請先停止目前工作，再重試。');throw error;}
      finally{clearTimeout(timer);}
    }
    static portalJob(batch,itemId,company){
      const item=batch.items?.find(i=>i.id===itemId);
      if(!item)throw Error('找不到選取的職缺，請返回招募資料重新選擇。');
      if(item.salary_type!=='monthly'||item.currency!=='TWD')throw Error('Computer Use 表單目前只支援新台幣月薪。');
      const skills=(item.requirements||'').split(/[,，、;；\n]/).map(t=>t.trim()).filter(Boolean);
      if(skills.length>30||skills.some(t=>t.length>80))throw Error('請將任職條件分行，每項80字以內、最多30項，再交給 Computer Use。');
      return {title:item.title,company_name:company,district:item.location||'',headcount:item.quantity,
        description:item.description||'',required_skills:skills,trainable_skills:[],
        salary_mode:'RANGE',salary_min:item.salary_min,salary_max:item.salary_max,
        company_intro:'',shift:'',work_hours:'',schedule_system:'',employment_type:'',min_experience_months:0};
    }
    async createBatch(message){if(!this.token)throw Error('請先連接示範公司，再建立招募資料。');return this.request('/batches',{message});}
    async saveBatch(id,drafts,confirmSalary=false){
      const current=await this.request('/batches/'+id);
      if(current.status==='published')return current;
      const edits=drafts.map(d=>({id:d.backendItemId,body:{title:d.role,quantity:Number(d.hires),
        description:d.skills,requirements:d.requirements||'',location:d.address,
        salary_min:d.salaryMin===''||d.salaryMin==null?null:Number(d.salaryMin),
        salary_max:d.salaryMax===''||d.salaryMax==null?null:Number(d.salaryMax),
        salary_type:'monthly',currency:'TWD',confirm_salary:confirmSalary}}));
      if(edits.length!==current.items.length||new Set(edits.map(e=>e.id)).size!==edits.length||edits.some(e=>!current.items.some(i=>i.id===e.id)))throw Error('招募資料項目與後端不一致，請重新載入批次。');
      // Validate all items before the first write. Publishing remains transactional on the server.
      for(const {body:d} of edits){
        if(!d.title?.trim()||d.title.length>100||!Number.isInteger(d.quantity)||d.quantity<1||d.quantity>10000||!d.location?.trim()||!d.description?.trim())throw Error('請填妥職稱、人數（1–10000）、工作地點與工作內容。');
        if((d.salary_min===null)!==(d.salary_max===null)||d.salary_min!==null&&(!Number.isSafeInteger(d.salary_min)||!Number.isSafeInteger(d.salary_max)||d.salary_min<=0||d.salary_max<d.salary_min||d.salary_max>1000000000))throw Error('請完整填寫有效的月薪上下限。');
        if(confirmSalary&&(!d.requirements.trim()||d.salary_min===null))throw Error('刊登前請補齊每筆任職條件與月薪，並確認薪資。');
      }
      let result=current;
      for(const edit of edits)result=await this.request(`/batches/${id}/items/${edit.id}`,edit.body,'PUT');
      return result;
    }
    async publishBatch(id,drafts){
      const saved=await this.saveBatch(id,drafts,true);
      if(saved.status!=='published'){
        await this.request(`/batches/${id}/confirm`,{});
        try{await this.request(`/batches/${id}/publish`,{});}catch(error){
          // A lost response must not create a duplicate publication on retry.
          const state=await this.request('/batches/'+id);
          if(state.status!=='published')throw error;
        }
      }
      const items=new Set(saved.items.map(i=>i.id));
      return (await this.request('/job-postings')).filter(p=>items.has(p.batch_item_id));
    }
    static jobs(batch){
      if(!Array.isArray(batch.items)||!batch.items.length)throw Error('未辨識到職缺，請補充職稱與人數。');
      if(batch.items.length>20)throw Error(`批次 ${batch.id} 已儲存；目前展示一次最多載入20筆，請縮小需求後再建立。`);
      if(batch.items.some(i=>i.salary_type!=='monthly'||i.currency!=='TWD'))throw Error(`批次 ${batch.id} 已儲存；目前展示只支援新台幣月薪，不能將時薪或年薪當作月薪載入。`);
      return batch.items.map(i=>({backendItemId:i.id,role:i.title,hires:i.quantity,
        ...(i.location?{address:i.location}:{}),
        ...(i.description?{skills:i.description}:{}),requirements:i.requirements||'',
        salaryMin:i.salary_min??null,salaryMax:i.salary_max??null}));
    }
  }
  if(typeof module!=='undefined'&&module.exports)module.exports=RecruitmentAPI;else root.RecruitmentAPI=RecruitmentAPI;
})(typeof window!=='undefined'?window:globalThis);
