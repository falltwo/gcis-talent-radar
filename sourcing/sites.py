"""網站目錄：職類 → 可以找人的公開作品網站，以及搜尋網址與個人頁網址的辨識規則。

每個網站都在 2026-11-02 用無頭 Chrome 實測過搜尋頁；會擋自動瀏覽的網站標成不可用，
系統不嘗試繞過機器人驗證。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import quote, quote_plus, urlsplit

CATEGORIES = {
    "software": "軟體開發",
    "ai_data": "AI／資料",
    "design": "設計",
    "research": "研究",
}

# 條款禁止自動化，或屬於付費雇主帳號才能看的履歷庫：一律不開
BLOCKED_DOMAINS = {
    "linkedin.com": "LinkedIn 使用條款禁止自動化存取",
    "scholar.google.com": "Google Scholar 禁止自動化存取；研究類改用 OpenAlex",
    "104.com.tw": "人力銀行履歷庫需付費雇主帳號，自動化操作違反條款",
    "1111.com.tw": "人力銀行履歷庫需付費雇主帳號，自動化操作違反條款",
    "518.com.tw": "人力銀行履歷庫需付費雇主帳號，自動化操作違反條款",
    "yes123.com.tw": "人力銀行履歷庫需付費雇主帳號，自動化操作違反條款",
    "cakeresume.com": "人力銀行履歷庫需付費雇主帳號，自動化操作違反條款",
}

GITHUB_LANGUAGES = {
    "python", "java", "javascript", "typescript", "go", "rust", "c", "c++", "c#", "php", "ruby",
    "kotlin", "swift", "scala", "dart", "r", "matlab", "shell", "html", "css", "vue", "lua",
}


@dataclass(frozen=True)
class SearchTerms:
    skills: tuple[str, ...]
    location: Optional[str] = None  # 英文地名，例如 Taichung

    def text(self, *, with_location: bool = True) -> str:
        parts = list(self.skills)
        if with_location and self.location:
            parts.append(self.location)
        return " ".join(parts)


def _github_query(terms: SearchTerms) -> str:
    parts = [f"language:{s}" if s.lower() in GITHUB_LANGUAGES else s for s in terms.skills]
    if terms.location:
        loc = terms.location
        parts.append(f'location:"{loc}"' if " " in loc else f"location:{loc}")
    return " ".join(parts)


def _github(terms: SearchTerms) -> str:
    return f"https://github.com/search?q={quote_plus(_github_query(terms))}&type=users"


def _github_typed(terms: SearchTerms) -> str:
    """打進 GitHub 搜尋框的字：用 type:user 限定找人。"""
    return "type:user " + _github_query(terms)


def _stackoverflow(terms: SearchTerms) -> str:
    tag = (terms.skills[0] if terms.skills else "python").lower().replace(" ", "-")
    return f"https://stackoverflow.com/tags/{quote(tag)}/topusers"


def _huggingface(terms: SearchTerms) -> str:
    return f"https://huggingface.co/models?search={quote_plus(terms.text(with_location=False))}"


def _kaggle(terms: SearchTerms) -> str:
    return f"https://www.kaggle.com/search?q={quote_plus(terms.text())}"


def _dribbble(terms: SearchTerms) -> str:
    return f"https://dribbble.com/search/{quote(terms.text())}"


def _orcid(terms: SearchTerms) -> str:
    return f"https://orcid.org/orcid-search/search?searchQuery={quote(terms.text())}"


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    categories: tuple[str, ...]
    domains: tuple[str, ...]
    search_url: Optional[Callable[[SearchTerms], str]]
    profile_pattern: Optional[re.Pattern]
    reserved: frozenset[str] = field(default_factory=frozenset)
    # 搜尋結果頁只列作品時（例如模型 owner/name），從作品網址推回作者個人頁
    work_pattern: Optional[re.Pattern] = None
    # 個人頁會跳機器人驗證時改走官方 API（不繞過驗證）
    profile_api: Optional[str] = None
    # Jev 操作的起點：入口頁上有搜尋框，Jev 把 typed_query 打進去再送出；沒有就直接開 search_url
    entry_url: Optional[str] = None
    typed_query: Optional[Callable[[SearchTerms], str]] = None
    available: bool = True
    unavailable_reason: str = ""

    def profile_url(self, href: str) -> Optional[str]:
        """回傳正規化的個人頁網址；不是個人頁就回 None。"""
        href = href.split("#")[0].split("?")[0].rstrip("/")
        for pattern, build in ((self.profile_pattern, None), (self.work_pattern, "owner")):
            if pattern is None:
                continue
            m = pattern.match(href)
            if not m:
                continue
            handle = m.group(1)
            if handle.lower() in self.reserved:
                return None
            if build == "owner":
                return f"https://{self.domains[0]}/{handle}"
            return href
        return None


_GITHUB_RESERVED = frozenset("""
about account apps blog collections contact customer-stories enterprise events explore features
login logout marketplace new notifications open-source orgs organizations partners pricing pulls
readme resources search security settings site solutions sponsors team topics trending trust-center
why-github issues codespaces copilot signup join platform mcp models premium-support home dashboard
""".split())
_HF_RESERVED = frozenset("""
models datasets spaces docs pricing login join blog learn papers tasks enterprise settings
organizations storage chat collections languages posts hardware pro support inference
inference-endpoints api new search terms-of-service privacy
""".split())
_KAGGLE_RESERVED = frozenset("""
code datasets competitions models discussions discussion learn search cookies rankings docs terms
privacy contact account settings organizations benchmarks static about careers notebooks
""".split())
_DRIBBBLE_RESERVED = frozenset("""
shots hire jobs pro session signup signups stories services instantmatch designers tags search learn about
browse-project-briefs designer-advertising proposals uploads contact privacy terms for-designers hiring
advertise places resources cookie-policy
""".split())

SITES: dict[str, Site] = {s.id: s for s in [
    Site("github", "GitHub", ("software", "ai_data"), ("github.com",), _github,
         re.compile(r"^https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))$"), _GITHUB_RESERVED,
         entry_url="https://github.com/search?type=users", typed_query=_github_typed),
    Site("stackoverflow", "Stack Overflow", ("software",), ("stackoverflow.com",), _stackoverflow,
         re.compile(r"^https://stackoverflow\.com/users/(\d+)/[^/]+$"), profile_api="stackexchange"),
    Site("huggingface", "Hugging Face", ("ai_data",), ("huggingface.co",), _huggingface,
         re.compile(r"^https://huggingface\.co/([A-Za-z0-9][A-Za-z0-9._-]*)$"), _HF_RESERVED,
         work_pattern=re.compile(r"^https://huggingface\.co/([A-Za-z0-9][A-Za-z0-9._-]*)/[A-Za-z0-9._-]+$"),
         entry_url="https://huggingface.co/models", typed_query=lambda t: t.text(with_location=False)),
    Site("kaggle", "Kaggle", ("ai_data",), ("www.kaggle.com", "kaggle.com"), _kaggle,
         re.compile(r"^https://www\.kaggle\.com/([A-Za-z0-9_-]+)$"), _KAGGLE_RESERVED,
         entry_url="https://www.kaggle.com/search", typed_query=lambda t: t.text()),
    Site("dribbble", "Dribbble", ("design",), ("dribbble.com",), _dribbble,
         re.compile(r"^https://dribbble\.com/([A-Za-z0-9_-]+)$"), _DRIBBBLE_RESERVED,
         entry_url="https://dribbble.com/", typed_query=lambda t: t.text()),
    Site("orcid", "ORCID", ("research",), ("orcid.org",), _orcid,
         re.compile(r"^https://orcid\.org/(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$"),
         entry_url="https://orcid.org/orcid-search/search", typed_query=lambda t: t.text()),
    # Google Scholar 沒有官方 API 且禁止自動化，研究類改用 OpenAlex 官方 API
    Site("openalex", "OpenAlex", ("research",), ("openalex.org", "api.openalex.org"), None, None,
         profile_api="openalex"),
    Site("gitlab", "GitLab", ("software",), ("gitlab.com",), None, None, available=False,
         unavailable_reason="使用 Cloudflare 機器人驗證，系統不繞過驗證"),
    Site("behance", "Behance", ("design",), ("www.behance.net", "behance.net"), None, None, available=False,
         unavailable_reason="對自動瀏覽回應 HTTP 400，系統不繞過"),
]}


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def blocked_reason(url: str) -> Optional[str]:
    host = _host(url)
    for domain, reason in BLOCKED_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return reason
    return None


def site_for_url(url: str) -> Optional[Site]:
    host = _host(url)
    for site in SITES.values():
        if any(host == d or host.endswith("." + d) for d in site.domains):
            return site
    return None


def sites_for(categories: list[str], *, only: Optional[list[str]] = None) -> list[Site]:
    """依職類挑網站，保留目錄順序；`only` 可再限縮成指定網站。"""
    picked = [s for s in SITES.values() if set(s.categories) & set(categories)]
    if only:
        picked = [s for s in picked if s.id in set(only)]
    return picked


def catalog() -> list[dict]:
    """給前端的網站目錄。"""
    return [
        {
            "id": s.id, "name": s.name,
            "categories": [CATEGORIES[c] for c in s.categories],
            "available": s.available, "unavailable_reason": s.unavailable_reason or None,
        }
        for s in SITES.values()
    ] + [{"id": "personal", "name": "個人網站、部落格、作品集", "categories": ["所有職類"],
          "available": True, "unavailable_reason": None,
          "note": "不主動搜尋；只開候選人個人頁上自己留的網站連結"}]
