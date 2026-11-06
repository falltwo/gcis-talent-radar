"""Bounded, short-lived recruitment context; only validated HR fields are patched."""
import re
from copy import deepcopy
from types import SimpleNamespace
from .execution import employer_name
from .salary import verified_salary
from .intent import is_information_request

TTL_SECONDS=1800
CLEAR=re.compile(r'^(?:清除(?:對話)?(?:記憶|上下文)|忘記(?:先前|之前|剛才)(?:的)?(?:需求|內容)|重新開始)[。！!\s]*$')
SHARED=re.compile(r'^(?:都通用|都適用|兩個都適用|全部適用|全部一樣|兩個都一樣)[。！!\s]*$')
AFFIRM=re.compile(r'\s*(?:yes|yep|yeah|ok|okay|對|是|沒錯|確認|好|好的|可以)[。！!\s]*',re.I)


def brief_for(state):
    parts=[]
    if state.get('company'):parts.append('公司名稱：'+state['company'])
    for item in state.get('items',[]):
        title=item['title'];parts.append(f"{item['quantity']}位{title}")
        if item.get('salary_min') is not None:
            period={'monthly':'月薪','yearly':'年薪','hourly':'時薪'}[item.get('salary_type','monthly')]
            parts.append(f"{title}{period}{item['salary_min']}至{item['salary_max']}元")
        for key,label in [('description','工作內容'),('requirements','任職條件'),('location','工作地點')]:
            if item.get(key):parts.append(f"{title}{label}：{item[key]}")
    return '\n'.join(parts)


def snapshot(batch,previous):
    state={'items':deepcopy(batch['items']),'company':employer_name(SimpleNamespace(enabled=False),batch['original_text'],previous.get('company',''))}
    return state


def patch(state,text):
    if is_information_request(text):return None
    items=deepcopy(state.get('items',[]))
    if not items:return None
    titles=[item['title'] for item in items]
    if AFFIRM.fullmatch(text):
        if state.get('pending_salary'):
            return {'kind':'clarify','message':'請指定這筆薪資適用的職位；若全部適用，可以說「全部適用」。'}
        return {'kind':'ack','message':'已保留目前的招募條件。請在右側檢查填表結果，修改並儲存後再按「確認送審」。'}
    from .parser import NUM,number
    named=next((title for title in sorted(titles,key=len,reverse=True) if text.startswith(title)),None)
    if named:
        changed_count=re.fullmatch(rf'\s*(?:的)?(?:招募)?(?:人數)?\s*(?:改成|改為|改到|調整為|調整成)\s*({NUM})\s*(?:位|人|名|個)?[。\s]*',text[len(named):])
        if changed_count:
            value=number(changed_count[1])
            if not 1<=value<=10000:return {'kind':'clarify','message':'招募人數必須為1至10000。'}
            for item in items:
                if item['title']==named:item['quantity']=value
            return {'kind':'patch','state':{**state,'items':items}}
    count=re.fullmatch(rf'\s*(?:(全部|所有)(?:職位)?\s*)?(?:人數\s*)?(?:改成|改為|調整為|[:：])?\s*({NUM})\s*(?:位|人|名|個)[。\s]*',text)
    if count:
        value=number(count[2])
        if not 1<=value<=10000:return {'kind':'clarify','message':'招募人數必須為1至10000。'}
        if len(items)>1 and not count[1]:return {'kind':'clarify','message':'請指定要修改哪個職位的人數，或說「全部改成5位」。'}
        for item in items:item['quantity']=value
        return {'kind':'patch','state':{**state,'items':items}}
    if re.search(rf'(?:改成|改為|調整為)\s*{NUM}\s*(?:位|人|名|個)',text):
        return {'kind':'clarify','message':'請指定目前要修改的職位與人數；目前職位為：'+'、'.join(titles)+'。'}
    # Complete new role/count requests belong to intake, not an update of old roles.
    from .parser import parse
    try:parse(text,include_salary=False)
    except ValueError:pass
    else:return None
    salary_text=text
    if SHARED.fullmatch(text) and state.get('pending_salary'):
        salary_text='全部'+state['pending_salary']
    if re.search(r'月薪|年薪|時薪|薪資|薪水|待遇',salary_text) and not re.search(r'[?？]|行情|平均|多少|查詢|搜尋|工作內容',salary_text):
        try:values=verified_salary(salary_text,titles)
        except ValueError as exc:
            return {'kind':'clarify','message':str(exc),'pending_salary':salary_text}
        if not values:return None
        for item in items:item.update(values.get(item['title'],{}))
        return {'kind':'patch','state':{**state,'items':items,'pending_salary':None}}
    company=employer_name(SimpleNamespace(enabled=False),text,'')
    if company:
        return {'kind':'patch','state':{**state,'company':company,'pending_salary':None}}
    field_text=text;targets=items
    shared=re.match(r'^(?:全部|所有)(?:職位)?\s*',text)
    if named:field_text=text[len(named):];targets=[item for item in items if item['title']==named]
    elif shared:field_text=text[shared.end():]
    match=re.fullmatch(r'\s*(地點|工作地點|地址|工作內容|任職條件|必要技能)\s*(?:改成|改為|改到|是|為|[:：])\s*(.+)',field_text,re.S)
    if match:
        if len(items)>1 and not (named or shared):return {'kind':'clarify','message':'請指定要修改哪個職位，或明確說明全部職位都適用。'}
        field={'地點':'location','工作地點':'location','地址':'location','工作內容':'description','任職條件':'requirements','必要技能':'requirements'}[match[1]]
        for item in targets:item[field]=match[2].strip()
        return {'kind':'patch','state':{**state,'items':items,'pending_salary':None}}
    return None
