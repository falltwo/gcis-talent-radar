import re

DIGITS = dict(zip('零一二三四五六七八九', range(10))) | {'兩': 2}
def number(text):
    text = text.replace(',', '')
    if text.isdigit(): return int(text)
    total = section = digit = 0
    for c in text:
        if c in DIGITS: digit = DIGITS[c]
        elif c in '十百千':
            section += (digit or 1) * {'十':10,'百':100,'千':1000}[c]; digit = 0
        elif c == '萬':
            total += (section + digit or 1) * 10000; section = digit = 0
        else: raise ValueError('無法辨識數字')
    return total + section + digit

NUM = r'[0-9零一二三四五六七八九十百千萬兩]+'

def valid_title(title):
    """Reject instruction fragments and merged roles instead of treating them as jobs."""
    return bool(title and len(title)<=100
                and not re.search(r'幫我|請幫|麻煩|我想|我要|幫忙|協助我|建立|新增|改成|改為|改到|調整|職缺表|履歷表|履歷範本|招募範本|表單範本',title)
                and not re.match(r'^(?:填寫|填表|套用|使用範本|送出|送審)',title)
                and title.count('工程師')<2
                and not re.search(rf'{NUM}\s*(?:個|位|名|人)',title))


def shared_headcounts(text):
    """Bind role lists to 各N位 before looking for legacy count-first phrases."""
    groups=list(re.finditer(rf'各\s*({NUM})\s*(?:個|位|名|人)',text))
    if not groups:return None
    # Mixed count-first/shared syntax remains the model's job; do not omit a role.
    markers=list(re.finditer(rf'({NUM})\s*(?:個|位|名|人)',text))
    if any(not any(g.start()<=m.start()<g.end() for g in groups) for m in markers):return None
    rows=[];cursor=0
    for group in groups:
        names=text[cursor:group.start()].strip(' \t\r\n，,、；;。')
        names=re.sub(r'^(?:(?:請|麻煩|幫我|協助我|我想|我要|我需要|想要|想|要|我們想|我們要|招募|招聘|徵求|找|建立|新增|聘請)\s*)+','',names)
        names=names.rsplit('：',1)[-1].strip()
        roles=[r.strip() for r in re.split(r'與|和|及|、|，|,',names) if r.strip()]
        if not roles or any(not valid_title(role) for role in roles):return None
        rows.extend({'title':role,'quantity':number(group[1])} for role in roles)
        cursor=group.end()
    return rows

def parse(text,include_salary=True):
    """Conservative deterministic parser: no invented titles, salaries, or LLM execution."""
    result=shared_headcounts(text)
    if result is None:
        role_first=list(re.finditer(rf'(?:^|[、，,；;\n。])\s*(?P<title>[^0-9零一二三四五六七八九十百千萬兩、，,；;\n。]+?)\s*(?P<count>{NUM})\s*(?:位|人|名|個)',text))
        if role_first and len(role_first)==len(list(re.finditer(rf'({NUM})\s*(?:個|位|名|人)',text))):
            candidates=[]
            for match in role_first:
                title=re.sub(r'^(?:我要|我想|我們要|我們想|要|想)?(?:在|於)[^，,。；;\n]{1,30}?(?:設廠|開廠|擴廠)\s*(?:招募|招聘|徵求|徵才)?\s*','',match['title']).strip()
                title=re.sub(r'^(?:(?:我要|我想|我們要|我們想)?(?:在|於)[^，,。；;\n]{1,20}區\s*(?:招募|招聘|徵求|徵才))\s*','',title)
                title=re.sub(r'^(?:(?:請|幫我|我想|我要|招募|招聘|徵求|找)\s*)+','',title).strip()
                title=re.sub(r'(?:需要|招募|招聘)\s*$','',title).strip()
                if title in {'各','都','全部'} or not valid_title(title):break
                candidates.append({'title':title,'quantity':number(match['count'])})
            if len(candidates)==len(role_first):result=candidates
    if result is None:
        markers=list(re.finditer(rf'({NUM})\s*(?:個|位|名|人)\s*',text))
        matches=[]
        for index,m in enumerate(markers):
            segment=text[m.end():markers[index+1].start() if index+1<len(markers) else len(text)]
            if re.match(r'(?:職位|職缺|職務)(?:各|都|均|皆|的|[，,；;。\s]|$)',segment):continue
            title=re.split(r'[、，,。；;\s]|月薪|時薪|年薪',segment)[0]
            if not valid_title(title):raise ValueError('職稱或人數歸屬不明確，請分別列出每個職位與人數；「幫我建立」不會當成職位。')
            matches.append((m[1],title))
        if not matches: raise ValueError('請補充要招募的職稱與人數，可以分次告訴我，不需要固定格式。')
        result = [dict(title=title,quantity=number(count)) for count,title in matches]
    if len({i['title'] for i in result}) != len(result): raise ValueError('重複職稱，請合併人數')
    if any(i['quantity'] < 1 or i['quantity'] > 10000 for i in result): raise ValueError('人數必須為 1–10000')
    from .salary import verified_salary
    salaries=verified_salary(text,[i['title'] for i in result]) if include_salary else {}
    for item in result:item.update(salaries.get(item['title'],{}))
    if len(result)==1:
        location=re.search(r'(?:在|於|工作地點\s*[:：])\s*((?:臺中市|台中市)?[\u4e00-\u9fff]{1,4}區)',text)
        if location:result[0]['location']=location[1]
    return result
