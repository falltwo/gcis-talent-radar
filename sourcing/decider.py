"""gpt-6-luna 負責決策：搜尋框要打什麼、搜尋結果裡先看哪幾位。Jev 只負責照做。

每個決定都有規則版備案（沒有金鑰或模型失敗時用），模型的輸出一律驗證後才採用。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from sourcing import llm
from sourcing import apis
from sourcing.planner import LOCATIONS, PERSONAL_TRAIT, Plan
from sourcing.sites import GITHUB_LANGUAGES, Site, github_ladder, github_parts

SYNTAX_HINTS = {
    "huggingface": "Hugging Face 模型搜尋：輸入模型或任務關鍵字，例如 chinese bert、speech recognition。",
    "kaggle": "Kaggle 搜尋：輸入主題關鍵字。",
    "dribbble": "Dribbble 作品搜尋：輸入設計類型關鍵字，例如 ui dashboard、branding。",
    "orcid": "ORCID 研究者搜尋：輸入研究領域或機構關鍵字。",
}


@dataclass(frozen=True)
class Card:
    """搜尋結果上的一位候選人：個人頁網址、顯示名稱、卡片上的文字。"""
    url: str
    name: str
    context: str = ""


def _clean_keyword(value: object) -> Optional[str]:
    """關鍵字最多兩個英文詞、不含個人特徵與地點，避免條件太多搜不到人。"""
    text = re.sub(r"\s+", " ", str(value or "")).strip().strip('"')
    if not text or len(text) > 30 or len(text.split()) > 2 or PERSONAL_TRAIT.search(text):
        return None
    if any(text.lower() == loc.lower() for loc in set(LOCATIONS.values())):
        return None
    return text


def _github_search(plan: Plan, need: int) -> tuple[str, str, str]:
    language, keyword = github_parts(plan.terms)
    source = "rules"
    if llm.has_key():
        out = llm.chat_json(
            "你替招募系統決定在 GitHub 找人時的搜尋條件。GitHub 找人時每個條件都要同時符合（比對個人頁的名字與自我介紹），"
            "條件越多越找不到人，所以只能給一個程式語言與一個關鍵字。language 從清單選或給 null；"
            "keyword 是一兩個英文詞，選大家自我介紹常寫的詞（例如 AI、backend、frontend、data），沒有就給 null。"
            "不可包含年齡、性別、國籍、婚育、宗教等個人特徵，也不要放地點。只回 JSON。",
            f"需求：{plan.query}\n技能：{', '.join(plan.terms.skills)}\n程式語言清單：{', '.join(sorted(GITHUB_LANGUAGES))}",
            "github_search", {"type": "object", "properties": {
                "language": {"type": ["string", "null"]}, "keyword": {"type": ["string", "null"]}},
                "required": ["language", "keyword"], "additionalProperties": False}, max_tokens=80)
        if out:
            lang = str(out.get("language") or "").lower() or None
            language = lang if lang in GITHUB_LANGUAGES else None
            keyword = _clean_keyword(out.get("keyword"))
            source = "llm"
    ladder = github_ladder(plan.terms.location, language, keyword)
    tried: list[str] = []
    for query in ladder:
        count = apis.github_user_count(query)
        if count is None:  # 官方 API 暫時不能用（例如超過次數）：用中間寬度的條件
            pick = ladder[min(1, len(ladder) - 1)]
            return pick, source, "無法先確認結果數"
        tried.append(f"{query}（{count} 人）")
        if count >= need:
            note = "" if query == ladder[0] else "條件太多找不到人，已放寬：" + " → ".join(tried)
            return query, source, note
    return ladder[-1], source, "已放寬到最寬的條件：" + " → ".join(tried)


def search_text(site: Site, plan: Plan, *, need: int = 3) -> tuple[str, str, str]:
    """回傳 (要打進搜尋框的字, 來源 llm|rules, 說明)。"""
    if site.id == "github":
        query, source, note = _github_search(plan, need)
        return "type:user " + query, source, note  # 沒加 type:user 會搜到 repo 而不是人
    fallback = site.typed_query(plan.terms) if site.typed_query else plan.terms.text()
    if not llm.has_key():
        return fallback, "rules", ""
    out = llm.chat_json(
        "你替招募系統決定要在網站搜尋框輸入什麼，才能找到符合需求的人。這個網站的搜尋不能依地點篩，不要放地點；"
        "query 只放一到三個最關鍵的英文詞，條件太多會搜不到。不可包含年齡、性別、國籍、婚育、宗教等個人特徵。只回 JSON。"
        + SYNTAX_HINTS.get(site.id, ""),
        f"網站：{site.name}\n需求：{plan.query}\n技能：{', '.join(plan.terms.skills)}\n參考寫法：{fallback}",
        "search_query", {"type": "object", "properties": {"query": {"type": "string"}},
                         "required": ["query"], "additionalProperties": False}, max_tokens=80)
    query = re.sub(r"\s+", " ", str((out or {}).get("query", ""))).strip()
    if not query or len(query) > 40 or len(query.split()) > 3 or PERSONAL_TRAIT.search(query):
        return fallback, "rules", ""
    return query, "llm", ""


def pick_candidates(site: Site, plan: Plan, cards: list[Card], k: int) -> tuple[list[Card], str]:
    """從搜尋結果挑出最值得點進去的 k 位，回傳 (名單, 來源)。模型只能從清單裡挑。"""
    if not cards:
        return [], "rules"
    if not llm.has_key() or len(cards) <= k:
        return cards[:k], "rules"
    listing = "\n".join(f"{i}. {c.name}｜{c.context[:240]}" for i, c in enumerate(cards[:20]))
    out = llm.chat_json(
        "你替 HR 從搜尋結果挑出最可能符合需求的人，依符合程度排序。只能用編號，只根據卡片上的專業資訊判斷，"
        "不可依年齡、性別、國籍、外貌等個人特徵挑選。只回 JSON。",
        f"網站：{site.name}\n需求：{plan.query}\n技能：{', '.join(plan.terms.skills)}\n"
        f"要挑 {k} 位。搜尋結果：\n{listing}",
        "pick", {"type": "object", "properties": {"picks": {"type": "array", "items": {"type": "integer"}}},
                 "required": ["picks"], "additionalProperties": False}, max_tokens=120)
    picks: list[Card] = []
    for i in (out or {}).get("picks", []):
        if isinstance(i, int) and 0 <= i < min(len(cards), 20) and cards[i] not in picks:
            picks.append(cards[i])
    if not picks:
        return cards[:k], "rules"
    return picks[:k], "llm"
