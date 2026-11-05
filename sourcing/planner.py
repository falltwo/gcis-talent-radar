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

# re.ASCII：\b 只把英文字母數字當成字，中文緊接英文（AI工程師、UI設計師）才分得開
CATEGORY_RULES: dict[str, re.Pattern] = {
    "software": re.compile(
        r"軟體|軟件|程式|工程師.*(?:後端|前端|全端)|後端|前端|全端|韌體|開發者|\b(?:software|developer|engineer|backend|"
        r"front-?end|full-?stack|devops|sre|android|ios|web)\b|python|java|javascript|typescript|react|golang|\bgo\b|rust|"
        r"kotlin|swift|\bphp\b|node\.?js|c\+\+|c#", re.I | re.ASCII),
    "ai_data": re.compile(
        r"\bai\b|人工智慧|機器學習|深度學習|資料科學|數據科學|資料分析|數據分析|資料工程|大型語言模型|電腦視覺|自然語言|"
        r"\b(?:ml|llm|nlp|machine\s+learning|deep\s+learning|data\s+scien\w*|data\s+analy\w*|data\s+engineer\w*|"
        r"computer\s+vision|pytorch|tensorflow|kaggle)\b", re.I | re.ASCII),
    "design": re.compile(
        r"設計師|視覺設計|平面設計|介面設計|產品設計|品牌設計|插畫|動畫|\b(?:ui|ux|designer|illustrat\w*|figma|"
        r"graphic\s+design|motion\s+design)\b", re.I | re.ASCII),
    "research": re.compile(r"研究員|研究人員|學者|博士後|教授|\b(?:researcher|postdoc|professor|research\s+scientist)\b", re.I | re.ASCII),
}

# 網路上少有公開作品的職類：沒命中上面任何職類時才用來給建議
NO_PUBLIC_WORK = re.compile(
    r"作業員|技術員|操作員|業務|會計|出納|行政|助理|司機|門市|店員|倉管|物流|品管|品檢|護理|保全|清潔|廚師|"
    r"客服|人資|採購|總機|收銀|領班|組長|焊工|水電|黑手|搬運", re.I)

SKILL_WORDS = [
    "ai", "python", "java", "javascript", "typescript", "golang", "go", "rust", "kotlin", "swift", "php", "ruby", "c++",
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
# 只找台灣的人：台灣的 22 個縣市（中文 → 英文），加上「台灣」整體。第一個中文寫法是顯示用的名稱
LOCATIONS = {
    "台中": "Taichung", "臺中": "Taichung", "台北": "Taipei", "臺北": "Taipei", "新北": "New Taipei",
    "桃園": "Taoyuan", "新竹": "Hsinchu", "苗栗": "Miaoli", "彰化": "Changhua", "南投": "Nantou",
    "雲林": "Yunlin", "嘉義": "Chiayi", "台南": "Tainan", "臺南": "Tainan", "高雄": "Kaohsiung",
    "屏東": "Pingtung", "宜蘭": "Yilan", "花蓮": "Hualien", "台東": "Taitung", "臺東": "Taitung",
    "基隆": "Keelung", "澎湖": "Penghu", "金門": "Kinmen", "連江": "Lienchiang", "馬祖": "Lienchiang",
    # 台中常見的行政區（HR 常直接寫區名）
    "西屯": "Taichung", "北屯": "Taichung", "南屯": "Taichung", "大雅": "Taichung", "太平": "Taichung",
    "大里": "Taichung", "豐原": "Taichung", "烏日": "Taichung", "沙鹿": "Taichung", "潭子": "Taichung",
    "台灣": "Taiwan", "臺灣": "Taiwan",
}
TAIWAN = "Taiwan"
DEFAULT_LOCATION = "Taichung"  # 沒寫地點時先找台中，再找台灣其他地區
TAIWAN_PLACES = frozenset(LOCATIONS.values())
# 台灣以外的地點：找人範圍只限台灣，寫到這些就擋下（規則版；有金鑰時另由 gpt-6-luna 判斷）
OUTSIDE_TAIWAN = re.compile(
    r"日本|東京|大阪|京都|韓國|首爾|中國(?!醫藥|文化|科技|信託|鋼鐵|石油|生產力)|中國大陸|北京|上海|深圳|廣州|杭州|香港|澳門|新加坡|馬來西亞|吉隆坡|泰國|曼谷|"
    r"越南|胡志明|河內|菲律賓|印尼|印度|美國|紐約|舊金山|矽谷|西雅圖|洛杉磯|加拿大|多倫多|溫哥華|英國|倫敦|"
    r"德國|柏林|法國|巴黎|荷蘭|阿姆斯特丹|歐洲|澳洲|雪梨|墨爾本|紐西蘭|"
    r"(?<![A-Za-z])(?:japan|tokyo|osaka|korea|seoul|china|beijing|shanghai|shenzhen|hong\s*kong|macau|singapore|"
    r"malaysia|thailand|bangkok|vietnam|india|usa|united\s+states|new\s+york|san\s+francisco|seattle|"
    r"canada|toronto|vancouver|london|germany|berlin|france|paris|europe|australia|sydney|melbourne)(?![A-Za-z])",
    re.I)
DEFAULT_SKILL = {"software": "python", "ai_data": "machine learning", "design": "ui", "research": "machine learning"}


@dataclass
class Plan:
    query: str
    categories: list[str]
    terms: SearchTerms
    has_public_work: bool
    source: str = "rules"  # rules | llm
    notes: list[str] = field(default_factory=list)
    location_default: bool = False  # 需求沒寫地點，用預設的台中
    outside_taiwan: str = ""  # 需求寫到台灣以外的地點（找人範圍只限台灣，這種需求會被擋下）

    def as_dict(self) -> dict:
        primary = self.terms.location or DEFAULT_LOCATION
        return {
            "categories": [{"id": c, "name": CATEGORIES[c]} for c in self.categories],
            "skills": list(self.terms.skills),
            "location": self.terms.location,
            # 找人範圍：先找 primary，不夠再找台灣其他地區（primary 就是台灣時只有一層）
            "search_area": {"primary": primary, "primary_label": place_label(primary),
                            "fallback": None if primary == TAIWAN else TAIWAN,
                            "default": self.location_default},
            "has_public_work": self.has_public_work,
            "source": self.source,
            "notes": self.notes,
        }


def place_label(location: Optional[str]) -> str:
    """英文地名換回中文給 HR 看（Taichung → 台中），沒有對照就用原文。"""
    return next((zh for zh, en in LOCATIONS.items() if en == location), location or "")


def _rule_location(text: str) -> Optional[str]:
    """需求裡的台灣地點：縣市優先於「台灣」，長的名字優先（New Taipei 不會被當成 Taipei）。"""
    lower = text.lower()
    found = [en for zh, en in LOCATIONS.items() if zh in text]
    found += [en for en in sorted(TAIWAN_PLACES, key=len, reverse=True)
              if re.search(rf"(?<![a-z]){re.escape(en.lower())}(?![a-z])", lower)]
    return next((f for f in found if f != TAIWAN), found[0] if found else None)


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
    location = _rule_location(text)
    outside = OUTSIDE_TAIWAN.search(text)
    if categories and not skills:
        skills = [DEFAULT_SKILL[categories[0]]]
    has_public_work = bool(categories)
    notes = []
    if not categories and NO_PUBLIC_WORK.search(text):
        notes.append("這類職缺網路上少有公開作品，建議改用職缺刊登、職訓單位等其他管道。")
    elif not categories:
        notes.append("看不出職類；請寫明職缺名稱或技能，例如「Python 後端工程師」「UI 設計師」。")
    return Plan(text, categories, SearchTerms(tuple(skills[:4]), location or DEFAULT_LOCATION), has_public_work,
                "rules", notes, location_default=location is None,
                outside_taiwan=outside.group(0) if outside and location is None else "")


_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {"type": "array", "items": {"type": "string", "enum": list(CATEGORIES)}},
        "skills": {"type": "array", "items": {"type": "string"}},
        "location": {"type": ["string", "null"], "enum": sorted(TAIWAN_PLACES) + ["outside_taiwan", None]},
        "has_public_work": {"type": "boolean"},
    },
    "required": ["categories", "skills", "location", "has_public_work"],
    "additionalProperties": False,
}
_LLM_SYSTEM = (
    "你把招募需求轉成搜尋公開作品網站用的條件。categories 只能用 software、ai_data、design、research；"
    "skills 是 1 到 4 個英文搜尋標籤（程式語言、框架、工具、領域），不要放年齡、性別、國籍、婚育、宗教等個人特徵；"
    "location 是需求指定的台灣縣市（從清單選，台中的行政區選 Taichung；只說台灣選 Taiwan），"
    "需求指定台灣以外的地點給 outside_taiwan，沒寫地點給 null；has_public_work 表示這個職類的人通常會在網路上公開作品。只回 JSON。"
)
PERSONAL_TRAIT = re.compile(r"\b(?:male|female|man|woman|men|women|age|young|old|married|single|nationality|religion)\b|"
                            r"男|女|歲|年輕|已婚|未婚|國籍|宗教", re.I | re.ASCII)


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
    location = out.get("location") if out.get("location") in TAIWAN_PLACES | {"outside_taiwan"} else None
    outside = base.outside_taiwan
    if location == "outside_taiwan":
        # 需求裡明確寫了台灣的地點就照台灣的找；否則擋下
        outside = "" if not base.location_default else (outside or "台灣以外的地點")
        location = None
    if not base.location_default:
        location = location or base.terms.location
    return Plan(base.query, categories, SearchTerms(tuple(skills), location or DEFAULT_LOCATION),
                bool(out.get("has_public_work")) and bool(categories), "llm", base.notes,
                location_default=location is None, outside_taiwan=outside)
