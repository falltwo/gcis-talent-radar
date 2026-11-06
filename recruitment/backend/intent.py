"""Recognize information requests before interpreting text as hiring evidence."""
import re


def is_information_request(text):
    # Assigned prose can itself contain words such as "如何". Inspect the intent
    # before the field label, rather than treating its value as a new question.
    assignment=re.search(r'(?:工作內容|工作職責|任職條件|必要技能)\s*[:：]',text)
    if assignment:text=text[:assignment.start()]
    # Questions remain questions even when they mention a headcount or salary.
    if re.search(r'請問|想了解|想知道|查詢|搜尋|查一下|查一查|行情|平均|多少|哪些|什麼|甚麼|如何|怎麼|是否|有沒有', text):
        return True
    writing = re.search(r'招募|招聘|徵才|徵求|聘請|建立|建表|填表|新增|改成|改為|調整為', text)
    if re.search(r'[?？]', text) and not writing:
        return True
    # A field assignment or an explicit hiring instruction supplies conditions.
    if assignment or writing or re.search(r'(?:工作內容|工作職責|任職條件|必要技能|工作地點|公司名稱)\s*[:：是為]', text):
        return False
    return bool(re.search(r'工作內容|工作職責|任職條件|必要技能|技能要求|經驗要求|工作能力|日常工作', text))
