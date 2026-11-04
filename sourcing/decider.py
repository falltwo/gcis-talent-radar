"""gpt-6-luna 負責決策：搜尋框要打什麼、搜尋結果裡先看哪幾位。Jev 只負責照做。

每個決定都有規則版備案（沒有金鑰或模型失敗時用），模型的輸出一律驗證後才採用。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sourcing import llm
from sourcing.planner import PERSONAL_TRAIT, Plan
from sourcing.sites import Site

SYNTAX_HINTS = {
    "github": "GitHub 搜尋語法：type:user 限定找人，language:python 指定語言，location:Taichung 指定地點。",
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


def search_text(site: Site, plan: Plan) -> tuple[str, str]:
    """回傳 (要打進搜尋框的字, 來源 llm|rules)。"""
    fallback = site.typed_query(plan.terms) if site.typed_query else plan.terms.text()
    if not llm.has_key():
        return fallback, "rules"
    out = llm.chat_json(
        "你替招募系統決定要在網站搜尋框輸入什麼，才能找到符合需求的人。只回 JSON，query 不超過 80 字，"
        "不可包含年齡、性別、國籍、婚育、宗教等個人特徵。" + SYNTAX_HINTS.get(site.id, ""),
        f"網站：{site.name}\n需求：{plan.query}\n技能：{', '.join(plan.terms.skills)}\n地點：{plan.terms.location or '不限'}\n"
        f"參考寫法：{fallback}",
        "search_query", {"type": "object", "properties": {"query": {"type": "string"}},
                         "required": ["query"], "additionalProperties": False}, max_tokens=120)
    query = re.sub(r"\s+", " ", str((out or {}).get("query", ""))).strip()
    if not query or len(query) > 80 or PERSONAL_TRAIT.search(query):
        return fallback, "rules"
    if site.id == "github" and "type:user" not in query:
        query = "type:user " + query  # 沒加就會搜到 repo 而不是人
    return query, "llm"


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
