"""Prepare suggestions from the existing occupational templates, before browser filling."""
import re
from types import SimpleNamespace
from pydantic import Field
from .ai import ModelOutput
from recruitment.taiwan_salary import get_reference


class JobSuggestion(ModelOutput):
    description:str=Field(min_length=10,max_length=1500)
    required_skills:list[str]=Field(min_length=1,max_length=8)
    trainable_skills:list[str]=Field(max_length=5)


def prepare_execution(ai,batch,company,district):
    from recruitment.job_research import find_template,history_for,draft_job,explicit_conditions
    from api.mock104 import JobForm
    original=batch['original_text'];items=batch['items']
    if not 1<=len(items)<=20:raise ValueError('每次最多處理20個職位，請分批提出需求。')
    results=[]
    for item in items:
        from .parser import valid_title
        role=item['title'];location=item.get('location') or district
        if not valid_title(role):raise ValueError('此筆職稱是填表指令或無效職稱，請重新提供真正的職位與人數。')
        if not location:location='臺中市'
        scoped=f"職位：{role}。招募{item['quantity']}位。"
        if item.get('description'):scoped+='工作內容：'+item['description']+'。'
        if item.get('requirements'):scoped+='任職條件：'+item['requirements']+'。'
        if item.get('salary_min') is not None:scoped+=f"月薪{item['salary_min']}至{item['salary_max']}元。"
        else:scoped+='薪資尚未指定，先標示面議建議。'
        # Reuse the supplied catalogue and public-role history before generating anything.
        try:known=bool(find_template(role) or history_for(role))
        except Exception:known=bool(find_template(role))
        if known:
            result=draft_job(SimpleNamespace(role=role,needs=scoped,company_name=company,company_intro='',district=location))
            job=result['job'];source=result['source'];sources=result['sources'];notes=result['review_notes']
        else:
            if ai.enabled:
                proposal=ai.structured(JobSuggestion,
                    '根據使用者的職稱與需求，擬定繁體中文企業招募表的工作內容及技能建議。這是待確認建議，不是已核准條件。'
                    '不能編造公司事實、薪資、證照或必須學歷。不以個人特徵篩選。技能每項最多80字。只輸出指定schema。',
                    {'role':role,'requirements':scoped})
                generated=proposal.model_dump();source='AI_SUGGESTION'
            else:
                generated={'description':f'負責{role}相關工作，依企業流程執行任務、記錄進度並協助團隊完成工作。', 'required_skills':['職務相關知識','溝通協調'],'trainable_skills':['公司內部作業流程']};source='GENERAL_TEMPLATE'
            job={'title':role,'company_name':company,'company_intro':'','district':location,'headcount':item['quantity'],
                 'salary_mode':'NEGOTIABLE','salary_min':None,'salary_max':None,'employment_type':'全職','shift':'日班',
                 'schedule_system':'固定班制','work_hours':'09:00–18:00','min_experience_months':0,**generated}
            sources=[];notes=['工作內容與技能為AI或通用範本建議，填完後請確認。']
        # Prefer conditions scoped to this role over general suggested defaults.
        scope=original
        if len(items)>1:
            start=original.find(role)
            if start>=0:
                following=[original.find(other['title'],start+len(role)) for other in items if other['title']!=role]
                end=min([p for p in following if p>=0],default=len(original))
                scope=original[start:end]
            else:scope=''
        explicit=explicit_conditions(scope)
        for key in ['shift','work_hours','schedule_system','employment_type','min_experience_months']:
            if key in explicit:job[key]=explicit[key]
        # Monetary values and quantities always come from the validated per-role extraction.
        job.update(title=role,company_name=company,district=location,headcount=item['quantity'])
        if item.get('salary_min') is not None:
            if item.get('salary_type')!='monthly':raise ValueError('目前求才網站填表支援新台幣月薪；請確認此職位的月薪條件。')
            job.update(salary_mode='RANGE',salary_min=item['salary_min'],salary_max=item['salary_max'])
        else:job.update(salary_mode='NEGOTIABLE',salary_min=None,salary_max=None)
        if item.get('description'):job['description']=item['description']
        if item.get('requirements'):
            skills=[v.strip() for v in re.split(r'[,，、;；\n]',item['requirements']) if v.strip()]
            if all(len(v)<=80 for v in skills) and len(skills)<=30:job['required_skills']=skills
            else:job['description']+='\n使用者指定任職條件：'+item['requirements']
        job=JobForm.model_validate(job).model_dump()
        salary_reference=get_reference(role,location)
        results.append({'job':job,'source':source,'sources':sources,
            'notes':list(dict.fromkeys([*notes,'未指定的全職、日班、固定班制、09:00–18:00及經驗不拘均先採用建議值。填完後請確認；薪資未指定時標示面議。'])),
            'suggested':True,'salary_reference':salary_reference})
    return results
