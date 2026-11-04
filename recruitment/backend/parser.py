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
def parse(text):
    """Conservative deterministic parser: no invented titles, salaries, or LLM execution."""
    matches = list(re.finditer(rf'({NUM})\s*(?:個|位|名)\s*([^、，,。；;\s]+)', text))
    if not matches: raise ValueError('請使用「三個工程師、兩個經理，經理月薪十萬元」格式；未解析內容請以草稿編輯補齊。')
    result = []
    for m in matches:
        title = re.split(r'月薪|時薪|年薪', m[2])[0]
        if not title or len(title) > 100: raise ValueError('職稱不明確')
        item = dict(title=title, quantity=number(m[1]))
        # Salary must explicitly name this title, or immediately follow its count/title.
        pattern = rf'{re.escape(title)}\s*(月薪|時薪|年薪)\s*({NUM}(?:,[0-9]{{3}})*)(?:\s*[至到~～-]\s*({NUM}(?:,[0-9]{{3}})*))?\s*元?'
        salaries = list(re.finditer(pattern, text))
        if len(salaries) > 1: raise ValueError(f'{title}有多個薪資指定，請先釐清')
        if salaries:
            s = salaries[0]
            lo = number(s[2]); hi = number(s[3]) if s[3] else lo
            if lo <= 0 or hi < lo: raise ValueError('薪資範圍不正確')
            item.update(salary_min=lo, salary_max=hi, salary_type={'月薪':'monthly','時薪':'hourly','年薪':'yearly'}[s[1]], currency='TWD', salary_source='hr_explicit', salary_provenance=s[0], salary_confirmed=True)
        result.append(item)
    if len({i['title'] for i in result}) != len(result): raise ValueError('重複職稱，請合併人數')
    if any(i['quantity'] < 1 or i['quantity'] > 10000 for i in result): raise ValueError('人數必須為 1–10000')
    # Unsupported salary expressions must never silently become template suggestions.
    remaining = text
    for i in result:
        if i.get('salary_provenance'): remaining = remaining.replace(i['salary_provenance'], '')
    if re.search(r'薪|薪水|薪資|待遇|萬|元|NT\$|TWD', remaining, re.I):
        raise ValueError('有無法安全對應職缺的薪資敘述，請明確指定「職稱月薪金額元」')
    return result
