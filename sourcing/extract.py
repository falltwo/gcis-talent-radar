"""從頁面擷取候選人：個人頁連結、作品連結、個人網站，以及專長摘要。

只處理公開頁面上看得到的內容；Email、電話一律移除，證據連結只用頁面上真的存在的網址。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional
from urllib.parse import urlsplit

from sourcing import apis, llm
from sourcing.planner import PERSONAL_TRAIT, Plan
from sourcing.sites import Site, blocked_reason, site_for_url

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\d)(?:\+?886[-\s]?|0)9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)|(?<!\d)\+?\d{1,3}[-\s]\d{2,4}[-\s]\d{3,4}[-\s]\d{3,4}(?!\d)")
NOISE = re.compile(r"cookie|privacy policy|terms of use|sign in|log in|off your first|use code|隱私|登入|優惠", re.I)
SOCIAL = {"twitter.com", "x.com", "facebook.com", "instagram.com", "youtube.com", "tiktok.com", "threads.com",
          "threads.net", "pinterest.com", "medium.com", "discord.gg", "t.me"}


@dataclass(frozen=True)
class Link:
    href: str
    text: str = ""
    rel: str = ""


@dataclass
class Candidate:
    site: str
    profile_url: str
    name: str
    headline: str = ""
    skills: list[str] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    summary: str = ""
    evidence: list[dict] = field(default_factory=list)
    personal_site: Optional[str] = None
    summary_source: str = "rules"  # rules | llm

    def as_dict(self) -> dict:
        return asdict(self)


def clean_text(text: str) -> str:
    """移除聯絡方式與無法編碼的字元（例如半個 emoji）。"""
    text = (text or "").encode("utf-8", "replace").decode("utf-8")
    text = EMAIL.sub("[已移除 Email]", text)
    return PHONE.sub("[已移除電話]", text)


def profile_links(site: Site, links: Iterable[Link], *, limit: int = 20) -> list[Link]:
    seen: dict[str, Link] = {}
    for link in links:
        url = site.profile_url(link.href)
        # 導覽列、頭像等沒有文字的連結不算候選人；同一人通常還有一個帶名字的連結
        if url and url not in seen and clean_text(link.text).strip():
            derived = url != link.href.split("#")[0].split("?")[0].rstrip("/")
            # 從作品推回作者時，連結文字是作品名稱，改用帳號當名字
            seen[url] = Link(url, url.rsplit("/", 1)[-1] if derived else clean_text(link.text).strip())
        if len(seen) >= limit:
            break
    return list(seen.values())


def work_links(site: Site, profile_url: str, links: Iterable[Link], *, limit: int = 3) -> list[Link]:
    """個人頁底下同一位作者的作品頁，例如 github.com/<user>/<repo>。"""
    prefix = profile_url.rstrip("/") + "/"
    out: dict[str, Link] = {}
    for link in links:
        href = link.href.split("#")[0].split("?")[0].rstrip("/")
        rest = href[len(prefix):] if href.startswith(prefix) else ""
        if rest and "/" not in rest and rest not in {"followers", "following", "repositories", "projects",
                                                      "packages", "stars", "sponsoring", "activity"}:
            out.setdefault(href, Link(href, clean_text(link.text).strip()[:60] or rest))
        if len(out) >= limit:
            break
    return list(out.values())


def personal_site(site: Site, links: Iterable[Link]) -> Optional[str]:
    """候選人自己在個人頁留的網站：只認 rel="me"，避免把頁面上的廣告或平台連結當成個人網站。"""
    for link in links:
        if "me" not in link.rel.lower().split():
            continue
        host = (urlsplit(link.href).hostname or "").lower().removeprefix("www.")
        if not link.href.startswith(("http://", "https://")) or not host:
            continue
        if blocked_reason(link.href) or site_for_url(link.href) or host in SOCIAL:
            continue
        return link.href
    return None


def _rule_summary(site: Site, profile_url: str, title: str, text: list[str], plan: Plan,
                  fallback_name: str) -> Candidate:
    body = " ".join(text)
    lower = body.lower()
    matched = [s for s in plan.terms.skills if s.lower() in lower]
    if re.fullmatch(r"[\d-]+X?", fallback_name or ""):
        fallback_name = ""  # ORCID 連結文字只是編號，改用頁面標題
    name = fallback_name or (re.split(r"[·|(]| - ", title)[0].strip() if title else "") or profile_url.rsplit("/", 1)[-1]
    headline = next((t for t in text if 12 <= len(t) <= 120 and name not in t and not t.startswith("/")
                     and ".md" not in t and not NOISE.search(t) and (" " in t or re.search(r"[一-鿿]", t))), "")
    return Candidate(site.id, profile_url, name[:80], headline[:120], matched, matched,
                     summary=f"頁面提到：{'、'.join(matched)}" if matched else "")


_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "headline": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["name", "headline", "skills", "summary"],
    "additionalProperties": False,
}
_SUMMARY_SYSTEM = (
    "你根據一位候選人的公開個人頁文字，整理給 HR 看的專長摘要。只能用頁面上出現的資訊，不可推測。"
    "name 用頁面上的顯示名稱或帳號；headline 是一句話的自我介紹；skills 最多 6 個專業技能；"
    "summary 用繁體中文 60 字內說明他的專長和代表作品。不要提及或推測年齡、性別、國籍、婚育、宗教、外貌、"
    "聯絡方式。只回 JSON。"
)


def summarize(site: Site, profile_url: str, title: str, text: list[str], links: list[Link], plan: Plan,
              *, fallback_name: str = "") -> Candidate:
    text = [clean_text(t) for t in text if t and t.strip()]
    cand = _rule_summary(site, profile_url, title, text, plan, fallback_name)
    if llm.has_key() and text:
        user = (f"職缺需要的技能：{', '.join(plan.terms.skills)}\n網站：{site.name}\n頁面標題：{clean_text(title)}\n"
                "頁面文字：\n" + "\n".join(text)[:6000])
        out = llm.chat_json(_SUMMARY_SYSTEM, user, "candidate_summary", _SUMMARY_SCHEMA, max_tokens=400)
        if out:
            skills = [clean_text(s)[:40] for s in out.get("skills", []) if isinstance(s, str)][:6]
            summary = clean_text(str(out.get("summary", "")))[:160]
            if PERSONAL_TRAIT.search(summary):
                summary = cand.summary  # 摘要提到個人特徵就不用模型的版本
            cand.name = clean_text(str(out.get("name") or cand.name))[:80]
            cand.headline = clean_text(str(out.get("headline") or cand.headline))[:120]
            cand.skills = [s for s in skills if not PERSONAL_TRAIT.search(s)]
            cand.summary = summary
            cand.summary_source = "llm"
    cand.evidence = [{"label": "個人頁", "url": profile_url}] + [
        {"label": w.text or "作品", "url": w.href} for w in work_links(site, profile_url, links)
    ]
    cand.personal_site = personal_site(site, links)
    if cand.personal_site:
        cand.evidence.append({"label": "個人網站", "url": cand.personal_site})
    return cand


def from_stackoverflow_api(site: Site, profile_url: str, plan: Plan, *, fallback_name: str = "") -> Optional[Candidate]:
    """Stack Overflow 個人頁會跳 Cloudflare 驗證，改用官方 API 讀公開資料。"""
    user_id = profile_url.rstrip("/").split("/")[-2]
    info = apis.stackoverflow_user(user_id)
    if not info:
        return None
    tags = [clean_text(t)[:40] for t in info["top_tags"]]
    matched = [s for s in plan.terms.skills if s.lower() in {t.lower() for t in tags}]
    bits = [f"Stack Overflow 聲望 {info['reputation']:,}" if isinstance(info["reputation"], int) else ""]
    if info["location"]:
        bits.append(clean_text(info["location"]))
    cand = Candidate(site.id, profile_url, clean_text(info["display_name"] or fallback_name)[:80],
                     "，".join(b for b in bits if b)[:120], tags, matched,
                     summary=f"最常回答的標籤：{'、'.join(tags)}" if tags else "", summary_source="api")
    cand.evidence = [{"label": "個人頁", "url": profile_url}]
    website = info["website_url"]
    if website and not blocked_reason(website) and not site_for_url(website):
        cand.personal_site = website
        cand.evidence.append({"label": "個人網站", "url": website})
    return cand
