'use strict';
(() => {
 const $=id=>document.getElementById(id),first=$('needs-form'),review=$('review-form');
 let busy=false,runId=null,timer=null;
 function setBusy(value){busy=value;for(const id of ['prepare','sample','quantum','approve'])$(id).disabled=value;}
 async function req(path,body,method='POST'){
  const r=await fetch('/api/mock104/'+path,{method,credentials:'same-origin',cache:'no-store',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:'請確認欄位格式與薪資方式。');return d;
 }
 function salary(){const nego=$('r-salary-mode').value==='NEGOTIABLE';for(const id of ['r-min','r-max']){$(id).disabled=nego;$(id).required=!nego;$(id).closest('.field').hidden=nego;$(id).setCustomValidity('');if(nego)$(id).value='';}}
 function sources(result){const box=$('research-sources');box.replaceChildren();box.hidden=false;const title=document.createElement('strong');title.textContent='參考來源與待確認建議';box.append(title);const ul=document.createElement('ul');for(const item of result.sources||[]){if(!item.url?.startsWith('https://'))continue;const li=document.createElement('li'),a=document.createElement('a');a.href=item.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=item.title||item.url;li.append(a);if(item.status==='CURATED_REFERENCE')li.append('（已整理的職業範本，非本次即時搜尋）');ul.append(li);}for(const text of result.review_notes||[]){const li=document.createElement('li');li.textContent=text;ul.append(li);}box.append(ul);}
 async function prepare(example=false){
  if(busy)return;if(example){$('role').value='會計';$('needs').value='招募三人，月薪面議。';}
  if(example==='QUANTUM'){$('role').value='量子研究師';$('needs').value='招募三人，月薪面議。';}if(!first.reportValidity())return;setBusy(true);$('error').hidden=true;$('status').textContent='正在查找職業範本或網路資料，保留你已提供的條件…';
  try{await req('start',{});const r=await req('agent/prepare',{company_name:$('company-name').value,company_intro:$('company-intro').value,district:$('district').value,role:$('role').value,needs:$('needs').value,mode:'AUTO'});
   for(const[name,value]of Object.entries(r.job)){const el=review.elements.namedItem(name);if(el){el.value=Array.isArray(value)?value.join('、'):value??'';el.closest('.field')?.classList.toggle('suggested',r.field_provenance?.[name]==='SUGGESTED');}}
   salary();sources(r);$('source').textContent=r.source==='LIVE_WEB_RESEARCH'?'即時網路搜尋建議':'具來源的職業範本';$('review-note').textContent='已保留你提供的人數與薪資方式。標示「建議／待確認」的內容由範本或網路補全，請核對公司的實際需求。';review.hidden=false;$('status').textContent='招募建議已產生，請確認或修改。';review.scrollIntoView({behavior:'smooth',block:'start'});
  }catch(e){$('error').textContent=e.message;$('error').hidden=false;$('status').textContent='尚未建立招募建議。';}finally{setBusy(false);}
 }
 async function poll(){try{const r=await req('agent/run',null,'GET');$('browser-phase').textContent=r.phase;$('browser-message').textContent=r.message||'正在準備獨立瀏覽器…';$('browser-resume').hidden=r.phase!=='AWAITING_CONFIRMATION';if(r.screenshot){$('browser-shot').src='data:image/jpeg;base64,'+r.screenshot;$('browser-shot').hidden=false;}if(['PUBLISHED','FAILED','CANCELLED'].includes(r.phase)){clearInterval(timer);$('browser-stop').disabled=r.phase!=='FAILED';}}catch(e){$('browser-message').textContent=e.message;clearInterval(timer);}}
 first.addEventListener('submit',e=>{e.preventDefault();prepare();});$('sample').addEventListener('click',()=>prepare(true));$('quantum').addEventListener('click',()=>prepare('QUANTUM'));$('r-salary-mode').addEventListener('change',salary);
 review.addEventListener('submit',async e=>{e.preventDefault();if(busy)return;salary();if($('r-salary-mode').value==='RANGE')$('r-max').setCustomValidity(Number($('r-max').value)<Number($('r-min').value)?'薪資上限不能低於下限。':'');if(!review.reportValidity())return;
  const job=Object.fromEntries(new FormData(review));for(const k of ['salary_min','salary_max','headcount','min_experience_months'])job[k]=['salary_min','salary_max'].includes(k)&&job.salary_mode==='NEGOTIABLE'?null:Number(job[k]);for(const k of ['required_skills','trainable_skills'])job[k]=job[k].split(/[,，、\n]/).map(x=>x.trim()).filter(Boolean);
  setBusy(true);$('error').hidden=true;try{const r=await req('agent/approve',{job,hr_confirmed:true,confirm_before_publish:$('second-confirm').checked,scenario:'SUCCESS'});runId=r.run_id;await req('agent/browser/start',{run_id:runId});$('browser-panel').hidden=false;$('browser-message').textContent='正在開啟獨立Chrome，請觀看實際的滑鼠鍵盤操作。';clearInterval(timer);timer=setInterval(poll,1500);await poll();$('browser-panel').scrollIntoView({behavior:'smooth'});}catch(e){$('error').textContent=e.message;$('error').hidden=false;}finally{setBusy(false);}
 });
 $('browser-resume').addEventListener('click',async()=>{try{await req('agent/browser/resume',{run_id:runId});await poll();}catch(e){$('browser-message').textContent=e.message;}});
 $('browser-stop').addEventListener('click',async()=>{try{await req('agent/cancel',{run_id:runId});await poll();}catch(e){$('browser-message').textContent=e.message;}});
 for(const id of ['r-min','r-max'])$(id).addEventListener('input',()=>$('r-max').setCustomValidity(''));
})();
