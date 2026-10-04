"""Local pattern-based hiring policy guard; limited coverage, not an LLM."""
import re
import unicodedata
from typing import Any, Dict

AGE = (r"年齡|年紀|歲數|[0-9零〇一二兩三四五六七八九十百]+(?:幾)?\s*歲|年輕|年長|中高齡|高齡"
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
# A previous hiring instruction can govern a short restriction in the next
# segment ("徵才廣告，限25歲以下"). Generic employee mentions alone are not an
# instruction to select people and must not turn demographic queries into bans.
ACTIVE_HIRING_CONTEXT = re.compile(
    r"招募|招聘|徵才|徵人|雇用|僱用|聘用|錄取|錄用|面試|履歷|候選人|求職者|應徵者|用人"
    r"|\b(?:hir(?:e|ing)|recruit\w*|applicant\w*|candidate\w*|interview\w*|resume\w*|selection)\b", re.I)
CONDITION_FRAGMENT = re.compile(
    r"^(?:限|只限|僅限|限定|條件(?:是|為)?|[0-9零〇一二兩三四五六七八九十百]+\s*歲(?:以上|以下|以內|以外))"
)
FAIR_HIRING_INTENT = re.compile(
    r"避免|防止|杜絕|不得歧視|不能歧視|不應歧視|反歧視|就業服務法|就服法|性別平等|就業保障|歧視.{0,16}(?:規定|法規|法律|權益|申訴)"
    r"|\b(?:avoid|prevent|fair|discrimination|employment\s+law)\b", re.I)
# An explicit selection action is necessary. A trait plus 'employee' alone is
# demographic context, not a request to use that trait in a hiring decision.
DISCRIMINATORY_DECISION_INTENT = re.compile(
    r"只\s*(?:招|聘|錄用|錄取|要)|不\s*(?:招|聘用|錄用|錄取)|限\s*(?:男|女)"
    r"|不要|排除|篩(?:掉|選|除|出)|挑(?:出|選)|選出|甄選|刷掉|淘汰|先?不考慮|只考慮|往後排|排(?:在)?(?:最?後|前)|優先|優先考慮"
    r"|以.{0,24}為(?:招募|招聘|錄取|聘用)?條件|(?:招募|招聘|錄取|聘用|徵才)條件(?:是|為|寫|限)"
    r"|(?:依|按照|根據).{0,12}(?:性別|年齡|國籍|種族|身心障礙|外貌).{0,12}(?:排序|錄取|排名)"
    r"|\b(?:only\s+(?:hire|recruit|select|employ)|(?:do\s+not|don't|never)\s+hire|exclude|reject|filter(?:\s+out)?|select|selection|choose|pick|shortlist|prioriti[sz]e|prefer|rank|screen(?:\s+out)?)\b", re.I)
# Generic hiring becomes a selection request when it directly constrains a
# protected group (e.g. 'hire candidates under 35' / '招募35歲以下').
HIRING_ACTION = re.compile(r"招募|招聘|徵才|雇用|僱用|聘用|錄取|錄用|\b(?:hire|employ|recruit|hiring)\b", re.I)
STATISTICAL_INTENT = re.compile(r"比例|人數|人口|結構|分布|分佈|趨勢|統計|\b(?:ratio|count|demographic\w*|trend\w*|statistics)\b", re.I)
# The negation must govern the selection action in this segment. An earlier
# fair-hiring phrase does not excuse a later, separate hiring instruction.
NEGATED_SELECTION = re.compile(
    r"(?:不得|禁止|避免|防止|不要|不應|不能|不可以|不以|未以)(?:(?!但|卻|同時|並且|仍然).){0,18}?(?:排除|篩選|篩掉|只招|只聘|只錄取|只考慮|錄取|雇用|僱用)"
    r"|(?:是否|有沒有|是否有).{0,8}(?:禁止|不得).{0,16}(?:排除|篩選|只招|只聘|只錄取)"
    r"|\b(?:avoid|prevent|prohibit(?:ed)?|forbid(?:den)?|must\s+not|should\s+not)\b.{0,45}"
    r"(?:exclud\w*|screen\w*|filter\w*|only\s+hir\w*|select\w*|discriminat\w*)", re.I)
ABILITY_CRITERION = re.compile(r"\b(?:by|based\s+on)\s+(?:skills?|qualifications?|experience)\b|(?:依|以|根據)(?:技能|能力|經驗|資格)(?:為準|篩選|挑選)", re.I)
ANAPHORA = re.compile(r"她們|他們|這些人|這群人|其(?:中)?(?:應徵者|候選人)|\b(?:them|those\s+(?:applicants|candidates))\b", re.I)
SEGMENT_BOUNDARY = re.compile(r"[。！？!?;；，,\n]+|(?:但|然而|卻|同時|並且|仍然|接著|然後|再)(?=只|把|以|招|聘|錄|排|篩|先)|\b(?:but|then|and)\b", re.I)


def inspect_hiring_prompt(query: str) -> Dict[str, Any]:
    text = unicodedata.normalize("NFKC", query or "").strip()
    text = re.sub(r"[‐‑–—]", "-", text)
    matched_traits = [label for label, pattern in PROTECTED_TRAITS.items() if pattern.search(text)]
    # Evaluate each instruction separately, so a statistical or legal clause
    # cannot cancel a later protected-trait selection instruction.
    clauses = [part.strip() for part in SEGMENT_BOUNDARY.split(text) if part.strip()]
    decision_request = False
    antecedent = False
    hiring_context_left = 0
    for clause in clauses:
        direct_traits = any(p.search(clause) for p in PROTECTED_TRAITS.values())
        traits = direct_traits or (antecedent and bool(ANAPHORA.search(clause)))
        explicit = bool(DISCRIMINATORY_DECISION_INTENT.search(clause))
        constrained_hiring = bool(
            HIRING_ACTION.search(clause)
            or (hiring_context_left and CONDITION_FRAGMENT.search(clause))
        ) and not STATISTICAL_INTENT.search(clause)
        negation = NEGATED_SELECTION.search(clause)
        # A second selection action after a prohibited/avoided action is a new
        # instruction, even when the writer omits punctuation or a connector.
        negated = bool(negation) and not bool(
            DISCRIMINATORY_DECISION_INTENT.search(clause, negation.end())
        )
        education_only = bool(FAIR_HIRING_INTENT.search(clause)) and not explicit
        ability_only = bool(ABILITY_CRITERION.search(clause)) and not direct_traits
        if traits and (explicit or constrained_hiring) and not negated and not education_only and not ability_only:
            decision_request = True
            break
        antecedent = direct_traits and bool(HIRING_CONTEXT.search(clause))
        hiring_context_left = 2 if ACTIVE_HIRING_CONTEXT.search(clause) else max(0, hiring_context_left - 1)
    blocked = bool(matched_traits) and decision_request
    return {
        "implementation": "HiringPatternGuard",
    "version": "hiring-pattern-v5",
        "decision": "REJECT" if blocked else "ALLOW",
        "policy_code": "FAIR_HIRING_PROTECTED_TRAIT",
        "matched_traits": matched_traits,
        "hiring_context": bool(HIRING_CONTEXT.search(text)),
        "active_hiring_context": bool(ACTIVE_HIRING_CONTEXT.search(text)),
        "fair_hiring_education": bool(FAIR_HIRING_INTENT.search(text)),
        "discriminatory_decision_request": decision_request,
        "reason": "系統不協助以受保護特徵作招募篩選、錄用或排序。" if blocked else "未命中本地招募歧視規則；不代表法律合規認證。",
    }
