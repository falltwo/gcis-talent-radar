"""網站目錄：職類 → 可以找人的公開作品網站，以及搜尋網址與個人頁網址的辨識規則。

每個網站都在 2026-11-02 用無頭 Chrome 實測過搜尋頁；會擋自動瀏覽的網站標成不可用，
系統不嘗試繞過機器人驗證。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit, urlunsplit

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

    def text(self, *, with_location: bool = True, max_skills: Optional[int] = None) -> str:
        parts = list(self.skills[:max_skills] if max_skills else self.skills)
        if with_location and self.location:
            parts.append(self.location)
        return " ".join(parts)


def github_parts(terms: SearchTerms) -> tuple[Optional[str], Optional[str]]:
    """GitHub 找人只放一個程式語言與一個關鍵字：條件是「全部都要符合」，多放就找不到人。"""
    language = next((s.lower() for s in terms.skills if s.lower() in GITHUB_LANGUAGES), None)
    keyword = next((s for s in terms.skills if s.lower() not in GITHUB_LANGUAGES), None)
    return language, keyword


def github_query(location: Optional[str], language: Optional[str], keyword: Optional[str]) -> str:
    parts = []
    if language:
        parts.append(f"language:{language}")
    if keyword:
        parts.append(f'"{keyword}"' if " " in keyword else keyword)
    if location:
        parts.append(f'location:"{location}"' if " " in location else f"location:{location}")
    return " ".join(parts)


def github_ladder(location: Optional[str], language: Optional[str], keyword: Optional[str]) -> list[str]:
    """由嚴到寬的搜尋條件：地點＋語言＋關鍵字 → 地點＋關鍵字 → 地點＋語言 → 只有地點。"""
    combos = [(language, keyword), (None, keyword), (language, None), (None, None)]
    out: list[str] = []
    for lang, kw in combos:
        q = github_query(location, lang, kw)
        if q and q not in out:
            out.append(q)
    return out


def _github_query(terms: SearchTerms) -> str:
    language, keyword = github_parts(terms)
    return github_query(terms.location, language, keyword)


def _github(terms: SearchTerms) -> str:
    return f"https://github.com/search?q={quote_plus(_github_query(terms))}&type=users"


def _github_typed(terms: SearchTerms) -> str:
    """打進 GitHub 搜尋框的字：用 type:user 限定找人。"""
    return "type:user " + _github_query(terms)


def _github_url(text: str) -> str:
    return f"https://github.com/search?q={quote_plus(text.replace('type:user', '').strip())}&type=users"


def _stackoverflow(terms: SearchTerms) -> str:
    tag = (terms.skills[0] if terms.skills else "python").lower().replace(" ", "-")
    return f"https://stackoverflow.com/tags/{quote(tag)}/topusers"


# Hugging Face、Kaggle、Dribbble 不能依地點搜尋，關鍵字也只放兩個，免得搜不到
def _short(terms: SearchTerms) -> str:
    return terms.text(with_location=False, max_skills=2)


def _huggingface(terms: SearchTerms) -> str:
    return f"https://huggingface.co/models?search={quote_plus(_short(terms))}"


def _kaggle(terms: SearchTerms) -> str:
    return f"https://www.kaggle.com/search?q={quote_plus(_short(terms))}"


def _dribbble(terms: SearchTerms) -> str:
    return f"https://dribbble.com/search/{quote(_short(terms))}"


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
    # 搜尋字 → 搜尋結果網址（Jev 沒打成功時直接開）
    query_url: Optional[Callable[[str], str]] = None
    # 搜尋結果怎麼看下一頁：(第一頁網址, 第幾頁) → 網址；None 表示往下捲動載入更多
    page_url: Optional[Callable[[str, int], str]] = None
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
         entry_url="https://github.com/search?type=users", typed_query=_github_typed, query_url=_github_url,
         page_url=lambda url, n: _with_param(url, "p", str(n))),
    # 網頁版連排行頁都會跳 Cloudflare 驗證，排行與個人資料都改用官方 Stack Exchange API，不開瀏覽器
    Site("stackoverflow", "Stack Overflow", ("software",), ("stackoverflow.com",), None,
         re.compile(r"^https://stackoverflow\.com/users/(\d+)/[^/]+$"), profile_api="stackexchange"),
    Site("huggingface", "Hugging Face", ("ai_data",), ("huggingface.co",), _huggingface,
         re.compile(r"^https://huggingface\.co/([A-Za-z0-9][A-Za-z0-9._-]*)$"), _HF_RESERVED,
         work_pattern=re.compile(r"^https://huggingface\.co/([A-Za-z0-9][A-Za-z0-9._-]*)/[A-Za-z0-9._-]+$"),
         entry_url="https://huggingface.co/models", typed_query=_short,
         query_url=lambda q: f"https://huggingface.co/models?search={quote_plus(q)}",
         page_url=lambda url, n: _with_param(url, "p", str(n - 1))),
    Site("kaggle", "Kaggle", ("ai_data",), ("www.kaggle.com", "kaggle.com"), _kaggle,
         re.compile(r"^https://www\.kaggle\.com/([A-Za-z0-9_-]+)$"), _KAGGLE_RESERVED,
         entry_url="https://www.kaggle.com/search", typed_query=_short,
         query_url=lambda q: f"https://www.kaggle.com/search?q={quote_plus(q)}"),
    Site("dribbble", "Dribbble", ("design",), ("dribbble.com",), _dribbble,
         re.compile(r"^https://dribbble\.com/([A-Za-z0-9_-]+)$"), _DRIBBBLE_RESERVED,
         entry_url="https://dribbble.com/", typed_query=_short,
         query_url=lambda q: f"https://dribbble.com/search/{quote(q)}"),
    # ORCID 網頁很重、常讓瀏覽器連線逾時，改用官方公開 API（不需金鑰），不開瀏覽器
    Site("orcid", "ORCID", ("research",), ("orcid.org", "pub.orcid.org"), None,
         re.compile(r"^https://orcid\.org/(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$"), profile_api="orcid"),
    # Google Scholar 沒有官方 API 且禁止自動化，研究類改用 OpenAlex 官方 API
    Site("openalex", "OpenAlex", ("research",), ("openalex.org", "api.openalex.org"), None, None,
         profile_api="openalex"),
    Site("gitlab", "GitLab", ("software",), ("gitlab.com",), None, None, available=False,
         unavailable_reason="使用 Cloudflare 機器人驗證，系統不繞過驗證"),
    Site("behance", "Behance", ("design",), ("www.behance.net", "behance.net"), None, None, available=False,
         unavailable_reason="對自動瀏覽回應 HTTP 400，系統不繞過"),
]}


def _with_param(url: str, key: str, value: str) -> str:
    """把網址的某個查詢參數設成指定值（沒有就加上）。"""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != key] + [(key, value)]
    return urlunsplit(parts._replace(query=urlencode(query)))


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
