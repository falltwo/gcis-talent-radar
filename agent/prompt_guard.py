"""Local pattern-based hiring policy guard; limited coverage, not an LLM."""
import re
import unicodedata
from typing import Any, Dict

AGE = (r"年齡|[0-9零〇一二兩三四五六七八九十百]+\s*歲|年輕|年長|中高齡|高齡"
       r"|\bage(?:d)?\b|\byoung\b|\bold\b|\b(?:under|over|below|above|younger\s+than|older\s+than)\s*\d{1,3}\b"
       r"|\b\d{1,3}\s*(?:-\s*\d{1,3}\s*)?(?:years?\s*old|歲)")
PROTECTED_TRAITS = {
    "性別／性別認同": re.compile(r"性別|(?:限|只招|只聘)\s*[男女]|男生|女生|男性|女性|男女|男員工|女員工|孕婦|懷孕|生育|婚育|婚姻|已婚|未婚|性傾向|哺乳|育兒|母親|父親|\b(?:male|female|men|women|pregnan\w*|married|unmarried|gender|sexual\s+orientation)\b", re.I),
    "年齡": re.compile(AGE, re.I),
    "種族／國籍／來源": re.compile(r"種族|族群|原住民|新住民|外籍|國籍|出生地|籍貫|母語|階級|思想|\b(?:race|ethnic\w*|nationality|foreign\w*|native\s+language)\b", re.I),
    "身心狀況／外貌": re.compile(r"身心障礙|身障|障礙|病史|疾病|健康狀況|外貌|外表|容貌|顏值|\b(?:disabilit\w*|disabled|medical\s+history|appearance)\b", re.I),
    "宗教／政治／工會": re.compile(r"宗教|政治立場|政黨|工會|工運|\b(?:religion|political\s+affiliation|union\s+membership)\b", re.I),
}
HIRING_CONTEXT = re.compile(
    r"招募|招聘|徵才|雇用|僱用|聘|錄用|錄取|面試|履歷|候選人|求職者|應徵|員工|職缺|用人|找人|人事|勞工"
    r"|\b(?:hir(?:e|ing)|recruit\w*|applicant\w*|candidate\w*|interview\w*|employment|employee\w*|resume\w*|selection)\b", re.I)
FAIR_HIRING_INTENT = re.compile(
    r"避免|防止|杜絕|不得歧視|不能歧視|不應歧視|反歧視|就業服務法|就服法|性別平等|就業保障|歧視.{0,16}(?:規定|法規|法律|權益|申訴)"
    r"|\b(?:avoid|prevent|fair|discrimination|employment\s+law)\b", re.I)
# An explicit selection action is necessary. A trait plus 'employee' alone is
# demographic context, not a request to use that trait in a hiring decision.
DISCRIMINATORY_DECISION_INTENT = re.compile(
    r"只\s*(?:招|聘|錄用|錄取|要)|不\s*(?:招|聘用|錄用|錄取)|限\s*(?:男|女)"
    r"|不要|排除|篩(?:掉|選|除|出)|挑(?:出|選)|選出|甄選|刷掉|淘汰|先?不考慮|往後排|排(?:在)?(?:最?後|前)|優先|優先考慮"
    r"|(?:依|按照|根據).{0,12}(?:性別|年齡|國籍|種族|身心障礙|外貌).{0,12}(?:排序|錄取|排名)"
    r"|\b(?:only\s+(?:hire|recruit|select|employ)|(?:do\s+not|don't|never)\s+hire|exclude|reject|filter(?:\s+out)?|select|selection|choose|pick|shortlist|prioriti[sz]e|prefer|rank|screen(?:\s+out)?)\b", re.I)
# Generic hiring becomes a selection request when it directly constrains a
# protected group (e.g. 'hire candidates under 35' / '招募35歲以下').
HIRING_ACTION = re.compile(r"招募|招聘|徵才|雇用|僱用|聘用|錄取|錄用|\b(?:hire|employ|recruit|hiring)\b", re.I)
STATISTICAL_INTENT = re.compile(r"比例|人數|人口|結構|分布|分佈|趨勢|統計|\b(?:ratio|count|demographic\w*|trend\w*|statistics)\b", re.I)


def inspect_hiring_prompt(query: str) -> Dict[str, Any]:
    text = unicodedata.normalize("NFKC", query or "").strip()
    text = re.sub(r"[‐‑–—]", "-", text)
    matched_traits = [label for label, pattern in PROTECTED_TRAITS.items() if pattern.search(text)]
    # Split sentences, not commas: mixed requests such as 'show statistics,
    # then only hire men' must still be rejected. Education/statistics never
    # overrides an explicit protected-trait selection request.
    clauses = re.split(r"[。！？!?;；\n]+", text)
    decision_request = False
    for clause in clauses:
        traits = any(p.search(clause) for p in PROTECTED_TRAITS.values())
        explicit = bool(DISCRIMINATORY_DECISION_INTENT.search(clause))
        constrained_hiring = bool(HIRING_ACTION.search(clause)) and not (
            FAIR_HIRING_INTENT.search(clause) or STATISTICAL_INTENT.search(clause)
        )
        if traits and (explicit or constrained_hiring):
            decision_request = True
            break
    blocked = bool(matched_traits) and decision_request
    return {
        "implementation": "HiringPatternGuard",
        "version": "hiring-pattern-v2",
        "decision": "REJECT" if blocked else "ALLOW",
        "policy_code": "FAIR_HIRING_PROTECTED_TRAIT",
        "matched_traits": matched_traits,
        "hiring_context": bool(HIRING_CONTEXT.search(text)),
        "fair_hiring_education": bool(FAIR_HIRING_INTENT.search(text)),
        "discriminatory_decision_request": decision_request,
        "reason": "系統不協助以受保護特徵作招募篩選、錄用或排序。" if blocked else "未命中本地招募歧視規則；不代表法律合規認證。",
    }
