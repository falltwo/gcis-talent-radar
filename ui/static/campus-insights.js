/* Render only the departments returned by the current campus search. */
(() => {
  'use strict';
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const safeLink=(text,url)=>{try{const u=new URL(url);if(!['https:','http:'].includes(u.protocol))return null;const a=node('a',text);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch{return null;}};
  window.renderCampusDepartments=(host,item)=>{
    const direct=new Map([...(item.matched_departments||[]),...(item.unlocated_department_matches||[])].map(d=>[d.department_id,d]));
    const related=new Map((item.related_departments||[]).filter(d=>!direct.has(d.department_id)).map(d=>[d.department_id,d]));
    host.replaceChildren();
    if(!direct.size&&!related.size){host.append(node('p','搜尋職務或科系名稱後，可查看符合與相關的科系。'));return;}
    const unlocated=new Set((item.unlocated_department_matches||[]).map(d=>d.department_id));
    for(const [title,group,careerLabel] of [['符合搜尋的科系',direct,'科系公開生涯進路'],['相關科系',related,'學類公開生涯進路']]){
      if(!group.size)continue;
      host.append(node('h3',title));const list=node('ul',null,'campus-department-list');
      group.forEach((dept,id)=>{
        const row=node('li');row.append(safeLink(dept.name,dept.website)||node('span',dept.name));
        for(const career of dept.career_matches||[]){
          const evidence=node('small',null,'campus-relation-note');
          const label=career.basis==='TRAINING'?'系所課程或培育方向':careerLabel;
          evidence.append(safeLink(`${label} · ${career.title}`,career.source_url)||node('span',career.title));
          row.append(evidence);
        }
        if(dept.registry_listed===0)row.append(node('small','名冊未列，招生狀態待查','campus-relation-note'));
        if(unlocated.has(id)||dept.location_status==='TEACHING_LOCATION_UNVERIFIED')row.append(node('small','教學校區待核驗','campus-relation-note'));
        else row.append(node('small','校區關聯依名冊，非逐系教學校區核驗','campus-relation-note'));
        list.append(row);
      });host.append(list);
    }
  };
})();
