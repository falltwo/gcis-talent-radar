"""Deterministic policy guard for discriminatory hiring requests."""
import re
from typing import Any, Dict, List


PROTECTED_TRAITS = {
    "性別／性別認同": re.compile(r"性別|男生|女生|男性|女性|男員工|女員工|孕婦|懷孕|生育|婚育|婚姻|性傾向|哺乳|育兒|母親|父親|\bmale\b|\bfemale\b|\bmen\b|\bwomen\b|\bpregnan\w*|\bsexual orientation\b", re.I),
    "年齡": re.compile(r"年齡|\d{2}\s*歲|年輕|年長|中高齡|高齡|\bage\b|\byoung\b|\bold\b", re.I),
    "種族／國籍／來源": re.compile(r"種族|族群|原住民|新住民|外籍|國籍|出生地|籍貫|母語|階級|語言|思想|\brace\b|\bethnic\w*|\bnationality\b|\bnative language\b", re.I),
    "身心狀況／外貌": re.compile(r"身心障礙|身障|障礙|病史|疾病|健康狀況|外貌|外表|容貌|顏值|\bdisabilit\w*|\bmedical history\b|\bappearance\b", re.I),
    "宗教／政治／工會": re.compile(r"宗教|政治立場|政黨|工會|工運|\breligion\b|\bpolitical affiliation\b|\bunion membership\b", re.I),
}

HIRING_CONTEXT = re.compile(
    r"招募|招聘|徵才|雇用|僱用|聘用|聘請|錄用|錄取|面試|篩選|履歷|候選人|求職者|應徵|員工|職缺|用人|找人|人事"
    r"|\bhiring\b|\brecruit\w*|\bapplicant\w*|\bcandidate\w*|\binterview\w*|\bemployment\b|\bjob opening\b|\bresume\b",
    re.I,
)

# Allow requests that clearly seek to prevent discrimination or understand
# employment protections. These patterns do not allow requests to apply a trait.
FAIR_HIRING_INTENT = re.compile(
    r"(?:如何|怎麼|如何在).{0,12}(?:避免|防止|杜絕).{0,12}(?:歧視|差別待遇)"
    r"|(?:反歧視|反性別歧視|就業服務法|性別平等法|年齡歧視).{0,16}(?:規定|法規|法律|權益|申訴|罰則|說明|介紹|解釋)"
    r"|(?:規定|法規|法律|權益|申訴|罰則|說明|介紹|解釋).{0,16}(?:反歧視|就業服務法|性別平等法|年齡歧視|性別歧視)"
)
DISCRIMINATORY_DECISION_INTENT = re.compile(
    r"只(?:招|聘|錄用|錄取|要)|(?:不要|不|拒絕)(?:招|聘用|錄用|錄取)"
    r"|排除|篩掉|刷掉|淘汰|拒絕錄取|優先(?:招募|聘用|錄取)|"
    r"(?:依|按照|根據).{0,8}(?:性別|年齡|國籍|種族|身心障礙|外貌).{0,8}(?:篩選|挑選|錄取|淘汰)"
)


def inspect_hiring_prompt(query: str) -> Dict[str, Any]:
    """Reject hiring decisions that use protected traits as selection criteria."""
    text = (query or "").strip()
    hiring_related = bool(HIRING_CONTEXT.search(text))
    matched_traits: List[str] = [
        label for label, pattern in PROTECTED_TRAITS.items() if pattern.search(text)
    ]
    fair_hiring_request = bool(FAIR_HIRING_INTENT.search(text))
    discriminatory_decision_request = bool(DISCRIMINATORY_DECISION_INTENT.search(text))

    blocked = bool(matched_traits) and (
        discriminatory_decision_request
        or (hiring_related and not fair_hiring_request)
    )
    return {
        "decision": "REJECT" if blocked else "ALLOW",
        "policy_code": "FAIR_HIRING_PROTECTED_TRAIT",
        "matched_traits": matched_traits,
        "hiring_context": hiring_related,
        "fair_hiring_education": fair_hiring_request,
        "discriminatory_decision_request": discriminatory_decision_request,
        "reason": (
            "不得以受保障特徵作為招募、面試、篩選或錄用條件。"
            if blocked else "未觸發招募歧視政策。"
        ),
    }
