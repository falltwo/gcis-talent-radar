"""把 HR 的需求轉成搜尋計畫：職類、搜尋條件、這個職類網路上有沒有公開作品。

先用本地規則判斷；有 OpenRouter 金鑰時再請 gpt-6-luna 補搜尋關鍵字，結果一律對照白名單驗證。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from sourcing import llm
from sourcing.sites import CATEGORIES, SearchTerms

CATEGORY_RULES: dict[str, re.Pattern] = {
    "software": re.compile(
        r"軟體|軟件|程式|工程師.*(?:後端|前端|全端)|後端|前端|全端|韌體|開發者|\b(?:software|developer|engineer|backend|"
        r"front-?end|full-?stack|devops|sre|android|ios|web)\b|python|java|javascript|typescript|react|golang|\bgo\b|rust|"
        r"kotlin|swift|\bphp\b|node\.?js|c\+\+|c#", re.I),
    "ai_data": re.compile(
        r"\bai\b|人工智慧|機器學習|深度學習|資料科學|數據科學|資料分析|數據分析|資料工程|大型語言模型|電腦視覺|自然語言|"
        r"\b(?:ml|llm|nlp|machine\s+learning|deep\s+learning|data\s+scien\w*|data\s+analy\w*|data\s+engineer\w*|"
        r"computer\s+vision|pytorch|tensorflow|kaggle)\b", re.I),
    "design": re.compile(
        r"設計師|視覺設計|平面設計|介面設計|產品設計|品牌設計|插畫|動畫|\b(?:ui|ux|designer|illustrat\w*|figma|"
        r"graphic\s+design|motion\s+design)\b", re.I),
    "research": re.compile(r"研究員|研究人員|學者|博士後|教授|\b(?:researcher|postdoc|professor|research\s+scientist)\b", re.I),
}

# 網路上少有公開作品的職類：沒命中上面任何職類時才用來給建議
NO_PUBLIC_WORK = re.compile(
    r"作業員|技術員|操作員|業務|會計|出納|行政|助理|司機|門市|店員|倉管|物流|品管|品檢|護理|保全|清潔|廚師|"
    r"客服|人資|採購|總機|收銀|領班|組長|焊工|水電|黑手|搬運", re.I)

SKILL_WORDS = [
    "python", "java", "javascript", "typescript", "golang", "go", "rust", "kotlin", "swift", "php", "ruby", "c++",
    "c#", "scala", "dart", "react", "vue", "angular", "node.js", "django", "flask", "fastapi", "spring",
    "kubernetes", "docker", "aws", "gcp", "azure", "terraform", "linux", "android", "ios", "flutter",
    "pytorch", "tensorflow", "llm", "nlp", "computer vision", "machine learning", "deep learning",
    "data science", "sql", "spark", "figma", "ui", "ux", "illustration", "branding", "motion design",
]
ZH_SKILLS = {
    "機器學習": "machine learning", "深度學習": "deep learning", "資料科學": "data science",
    "電腦視覺": "computer vision", "自然語言": "nlp", "大型語言模型": "llm", "介面設計": "ui",
    "插畫": "illustration", "品牌設計": "branding", "動畫": "motion design", "前端": "frontend",
    "後端": "backend", "全端": "fullstack",
}
LOCATIONS = {
    "台北": "Taipei", "臺北": "Taipei", "新北": "New Taipei", "桃園": "Taoyuan", "新竹": "Hsinchu",
    "台中": "Taichung", "臺中": "Taichung", "彰化": "Changhua", "台南": "Tainan", "臺南": "Tainan",
    "高雄": "Kaohsiung", "台灣": "Taiwan", "臺灣": "Taiwan",
}
DEFAULT_SKILL = {"software": "python", "ai_data": "machine learning", "design": "ui", "research": "machine learning"}


@dataclass
class Plan:
    query: str
    categories: list[str]
    terms: SearchTerms
    has_public_work: bool
    source: str = "rules"  # rules | llm
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "categories": [{"id": c, "name": CATEGORIES[c]} for c in self.categories],
            "skills": list(self.terms.skills),
            "location": self.terms.location,
            "has_public_work": self.has_public_work,
            "source": self.source,
            "notes": self.notes,
        }


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip()


def rule_plan(query: str) -> Plan:
    text = _normalize(query)
    lower = text.lower()
    categories = [c for c, pattern in CATEGORY_RULES.items() if pattern.search(text)]
    skills: list[str] = []
    for word in SKILL_WORDS:
        # 英文技能要整字比對，避免 "go" 命中 "google"
        if re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9+#])", lower) and word not in skills:
            skills.append(word)
    # 中文領域詞排在明確技術之後，搜尋時以使用者點名的技術優先
    for zh, en in ZH_SKILLS.items():
        if zh in text and en not in skills:
            skills.append(en)
    location = next((en for zh, en in LOCATIONS.items() if zh in text), None)
    if location is None:
        location = next((en for en in set(LOCATIONS.values()) if en.lower() in lower), None)
    if categories and not skills:
        skills = [DEFAULT_SKILL[categories[0]]]
    has_public_work = bool(categories)
    notes = []
    if not categories and NO_PUBLIC_WORK.search(text):
        notes.append("這類職缺網路上少有公開作品，建議改用職缺刊登、職訓單位等其他管道。")
    elif not categories:
        notes.append("看不出職類；請寫明職缺名稱或技能，例如「Python 後端工程師」「UI 設計師」。")
    return Plan(text, categories, SearchTerms(tuple(skills[:4]), location), has_public_work, "rules", notes)


_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {"type": "array", "items": {"type": "string", "enum": list(CATEGORIES)}},
        "skills": {"type": "array", "items": {"type": "string"}},
        "location": {"type": ["string", "null"]},
        "has_public_work": {"type": "boolean"},
    },
    "required": ["categories", "skills", "location", "has_public_work"],
    "additionalProperties": False,
}
_LLM_SYSTEM = (
    "你把招募需求轉成搜尋公開作品網站用的條件。categories 只能用 software、ai_data、design、research；"
    "skills 是 1 到 4 個英文搜尋標籤（程式語言、框架、工具、領域），不要放年齡、性別、國籍、婚育、宗教等個人特徵；"
    "location 是英文城市或國家名，沒有就給 null；has_public_work 表示這個職類的人通常會在網路上公開作品。只回 JSON。"
)
PERSONAL_TRAIT = re.compile(r"\b(?:male|female|man|woman|men|women|age|young|old|married|single|nationality|religion)\b|"
                            r"男|女|歲|年輕|已婚|未婚|國籍|宗教", re.I)


def plan(query: str) -> Plan:
    base = rule_plan(query)
    if not llm.has_key():
        return base
    out = llm.chat_json(_LLM_SYSTEM, base.query, "sourcing_plan", _LLM_SCHEMA, max_tokens=300)
    if not out:
        base.notes.append("模型暫時無法使用，改用本地規則判斷。")
        return base
    categories = [c for c in out.get("categories", []) if c in CATEGORIES] or base.categories
    skills = [s.strip().lower() for s in out.get("skills", []) if isinstance(s, str) and s.strip()]
    skills = [s for s in skills if not PERSONAL_TRAIT.search(s)][:4] or list(base.terms.skills)
    location: Optional[str] = out.get("location") if isinstance(out.get("location"), str) else None
    if location and PERSONAL_TRAIT.search(location):
        location = None
    return Plan(base.query, categories, SearchTerms(tuple(skills), location or base.terms.location),
                bool(out.get("has_public_work")) and bool(categories), "llm", base.notes)
