/* PR22 Computer Use endpoints → real screenshots inside the PR31 workbench. */
(function(root){
  'use strict';
  class RecruitmentLiveRun{
    constructor(request,onUpdate=()=>{},sleep=ms=>new Promise(r=>setTimeout(r,ms))){this.request=request;this.onUpdate=onUpdate;this.sleep=sleep;this.generation=0;this.runId=null;this.busy=false;this.results=[];}
    static prepare(jobs){
      return jobs.map((j,index)=>{
        try{
          const skills=String(j.requirements||'').split(/[,，、;；\n]/).map(t=>t.trim().toLowerCase()).filter(Boolean);
          const job={title:j.role?.trim(),company_name:j.company?.trim(),district:j.address?.trim(),headcount:Number(j.hires),
            description:j.skills?.trim(),required_skills:[...new Set(skills)],trainable_skills:[],
            salary_mode:'RANGE',salary_min:Number(j.salaryMin),salary_max:Number(j.salaryMax),company_intro:j.companyIntro?.trim()||'',
            shift:j.shift?.trim(),work_hours:j.workHours?.trim(),schedule_system:j.scheduleSystem,employment_type:j.employmentType,
            min_experience_months:Number(j.experienceYears||0)*12};
          for(const [key,label,max] of [['title','職稱',100],['company_name','公司名稱',120],['district','工作地點',80],['description','工作內容',5000],['shift','班別',80],['work_hours','上班時間',120]])if(!job[key]||job[key].length>max)throw Error(`請填妥${label}（最多${max}字）。`);
          if(job.description.length<10)throw Error('工作內容至少需要10個字。');
          if(!Number.isInteger(job.headcount)||job.headcount<1||job.headcount>10000)throw Error('招募人數須為1–10000的整數。');
          if(!Number.isSafeInteger(job.salary_min)||!Number.isSafeInteger(job.salary_max)||job.salary_min<1||job.salary_max<job.salary_min||job.salary_max>10000000)throw Error('請確認每筆月薪上下限為有效整數。');
          if(!skills.length||skills.length>30||skills.some(t=>t.length>80))throw Error('請填寫任職條件，每項80字以內、最多30項，以換行或逗號分隔。');
          if(!['固定班制','排班制','輪班制'].includes(job.schedule_system)||!['全職','兼職'].includes(job.employment_type))throw Error('請選擇班制及工作性質。');
          if(!Number.isInteger(job.min_experience_months)||job.min_experience_months<0||job.min_experience_months>600)throw Error('經驗要求須介於0至50年，且能換算成整數月。');
          return job;
        }catch(error){error.jobIndex=index;throw error;}
      });
    }
    static async publishFilled(results,request){
      if(!results.length||results.some(r=>r.phase!=='FILLED'||r.driver!=='COMPUTER_USE'||!r.job_id||!r.screenshot))throw Error('所有職位必須完成實際填表，才能確認刊登。');
      for(const result of results){
        const state=await request('state');let row=state.jobs.find(j=>j.id===result.job_id);
        if(!row||Object.keys(result.job).some(k=>JSON.stringify(row.data[k])!==JSON.stringify(result.job[k])))throw Error('網站表格與你確認的內容不同，請重新填表後再刊登。');
        for(const [status,action] of [['DRAFT','submit'],['PENDING_APPROVAL','approve'],['PROCESSING','complete']]){
          if(row.status===status){
            const updated=await request('jobs/'+row.id+'/'+action,action==='approve'?{scenario:'SUCCESS'}:{});
            row=updated.jobs.find(j=>j.id===result.job_id);
            if(!row)throw Error('無法核對刊登結果，請稍後重試。');
          }
        }
        if(row.status!=='SUCCEEDED')throw Error('此職位尚未刊登完成，請稍後重試。');
      }
    }
    static async submitReviewed(results,request){
      if(!results.length||results.some(r=>!r.human_reviewed||!['FILLED','REVIEW_REQUIRED'].includes(r.phase)||r.driver!=='COMPUTER_USE'||!r.job_id||!r.screenshot||!Number.isInteger(r.reviewed_revision)))throw Error('請逐筆檢查並儲存確認所有職缺後再送審。');
      // Check the entire batch first, then submit only the explicitly reviewed revisions.
      const state=await request('state');
      for(const result of results){const row=state.jobs.find(j=>j.id===result.job_id);if(!row||row.revision!==result.reviewed_revision||Object.keys(result.job).some(k=>JSON.stringify(row.data[k])!==JSON.stringify(result.job[k])))throw Error('職缺已變更，請重新檢查並儲存確認。');}
      for(const result of results){
        const current=await request('state'),row=current.jobs.find(j=>j.id===result.job_id);
        if(!row)throw Error('找不到本次職缺。');
        if(row.status==='DRAFT')await request('jobs/'+row.id+'/submit',{expected_revision:result.reviewed_revision});
        else if(!['PENDING_APPROVAL','PROCESSING','SUCCEEDED'].includes(row.status))throw Error('此職缺目前無法送審。');
      }
    }
    async waitReleased(){
      for(let attempt=0;attempt<20;attempt++){
        const state=await this.request('agent/run');
        if(!state.browser_active)return;
        await this.sleep(300);
      }
      throw Error('前一個瀏覽器仍在關閉中，請稍後重試。');
    }
    async stop(){
      this.generation++;
      if(this.runId){try{await this.request('agent/cancel',{run_id:this.runId});await this.waitReleased();}catch(error){if(error.status!==404)throw error;}this.runId=null;}
    }
    async start(jobs,options={}){
      if(this.busy)throw Error('正在填表，請勿重複開始。');
      this.busy=true;this.results=[];const generation=++this.generation;
      try{
        await this.request('start',{});
        for(let index=0;index<jobs.length;index++){
          if(generation!==this.generation)return;
          if(this.runId){try{await this.request('agent/cancel',{run_id:this.runId});await this.waitReleased();}catch(error){if(error.status!==404)throw error;}this.runId=null;}
          this.onUpdate({phase:'STARTING',index,total:jobs.length});
          const approved=await this.request('agent/approve',{job:jobs[index],hr_confirmed:!options.proposal,auto_fill:Boolean(options.proposal),confirm_before_publish:true,fill_only:true,scenario:'SUCCESS'});
          this.runId=approved.run_id;
          if(generation!==this.generation){await this.request('agent/cancel',{run_id:this.runId});return;}
          await this.request('agent/browser/start',{run_id:this.runId});
          let completed=false;
          for(let poll=0;poll<900;poll++){
            if(generation!==this.generation){await this.request('agent/cancel',{run_id:this.runId});return;}
            const run=await this.request('agent/run');
            if(run.run_id!==this.runId)throw Error('目前填表工作已被取代，請重新確認條件。');
            this.onUpdate({phase:run.phase,index,total:jobs.length,run});
            if(['FILLED','REVIEW_REQUIRED'].includes(run.phase)){
              if(!run.screenshot||!run.job_id||run.driver!=='COMPUTER_USE')throw Error('尚未取得實際填表完成證據，不能刊登。');
              this.results.push(run);completed=true;break;
            }
            if(['FAILED','CANCELLED'].includes(run.phase))throw Error(run.message||'填表已停止，尚未刊登。');
            await this.sleep(1000);
          }
          if(!completed)throw Error('填表等待逾時，請停止後重試。');
        }
        if(generation===this.generation)this.onUpdate({phase:'COMPLETE',index:jobs.length-1,total:jobs.length,results:this.results});
        return this.results;
      }catch(error){
        if(generation!==this.generation)return;
        this.onUpdate({phase:'FAILED',message:error.message,index:this.results.length,total:jobs.length});
        throw error;
      }finally{this.busy=false;}
    }
  }
  if(typeof module!=='undefined'&&module.exports)module.exports=RecruitmentLiveRun;else root.RecruitmentLiveRun=RecruitmentLiveRun;
})(typeof window!=='undefined'?window:globalThis);
