"""網站官方 API：個人頁會跳機器人驗證時改用官方 API 讀公開資料（不繞過驗證）。"""
from __future__ import annotations

from typing import Any, Optional

import requests

STACKEXCHANGE = "https://api.stackexchange.com/2.3"


def stackoverflow_users(user_ids: list[str], *, timeout: float = 15.0) -> Optional[dict[str, dict[str, Any]]]:
    """一次查最多 100 位的公開資料（顯示名稱、聲望、地點、網站）；先用來篩地點，省下逐一查詢。"""
    ids = [i for i in user_ids if i.isdigit()][:100]
    if not ids:
        return {}
    try:
        r = requests.get(f"{STACKEXCHANGE}/users/{';'.join(ids)}", params={"site": "stackoverflow", "pagesize": 100},
                         timeout=timeout)
        r.raise_for_status()
        items = r.json().get("items") or []
    except (requests.RequestException, ValueError):
        return None
    return {str(i.get("user_id")): {
        "display_name": i.get("display_name") or "", "reputation": i.get("reputation"),
        "location": i.get("location") or "", "website_url": i.get("website_url") or "", "link": i.get("link") or "",
    } for i in items}


def stackoverflow_top_answerers(tag: str, *, timeout: float = 15.0) -> Optional[list[tuple[str, str]]]:
    """標籤的歷來與本月回答排行（各最多 20 位），回傳 [(user_id, 顯示名稱)]，不重複。"""
    out: dict[str, str] = {}
    try:
        for period in ("all_time", "month"):
            r = requests.get(f"{STACKEXCHANGE}/tags/{tag}/top-answerers/{period}",
                             params={"site": "stackoverflow", "pagesize": 20}, timeout=timeout)
            r.raise_for_status()
            for item in r.json().get("items", []):
                user = item.get("user") or {}
                if user.get("user_id"):
                    out.setdefault(str(user["user_id"]), user.get("display_name") or "")
    except (requests.RequestException, ValueError):
        return None
    return list(out.items())


def stackoverflow_top_tags(user_id: str, *, timeout: float = 15.0) -> Optional[list[str]]:
    try:
        r = requests.get(f"{STACKEXCHANGE}/users/{user_id}/top-tags", params={"site": "stackoverflow", "pagesize": 6},
                         timeout=timeout)
        r.raise_for_status()
        return [t.get("tag_name") for t in r.json().get("items", []) if t.get("tag_name")]
    except (requests.RequestException, ValueError):
        return None


def stackoverflow_user(user_id: str, *, timeout: float = 15.0) -> Optional[dict[str, Any]]:
    """Stack Exchange 官方 API：公開的顯示名稱、聲望、地點、網站與最常回答的標籤。"""
    params = {"site": "stackoverflow"}
    try:
        user = requests.get(f"{STACKEXCHANGE}/users/{user_id}", params=params, timeout=timeout)
        user.raise_for_status()
        items = user.json().get("items") or []
        if not items:
            return None
        tags = requests.get(f"{STACKEXCHANGE}/users/{user_id}/top-tags", params={**params, "pagesize": 6},
                            timeout=timeout)
        tags.raise_for_status()
    except (requests.RequestException, ValueError):
        return None
    info = items[0]
    return {
        "display_name": info.get("display_name") or "",
        "reputation": info.get("reputation"),
        "location": info.get("location") or "",
        "website_url": info.get("website_url") or "",
        "link": info.get("link") or "",
        "top_tags": [t.get("tag_name") for t in tags.json().get("items", []) if t.get("tag_name")],
    }


OPENALEX = "https://api.openalex.org"
COUNTRY_CODES = {"Taiwan": "TW"}


def _tail(openalex_id: Optional[str]) -> str:
    """https://openalex.org/A123 → A123；空值回空字串（真實資料裡會有）。"""
    return (openalex_id or "").rsplit("/", 1)[-1]


def _openalex(path: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    response = requests.get(f"{OPENALEX}/{path}", params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def openalex_city_institutions(city: str, *, country: str = "TW", timeout: float = 20.0) -> list[tuple[str, str]]:
    """位在指定城市的機構 (id, 名稱)，例如 Taichung 的中興、東海、逢甲。"""
    found: list[tuple[str, str]] = []
    for page in range(1, 4):
        data = _openalex("institutions", {"filter": f"country_code:{country}", "per-page": 200, "page": page,
                                          "select": "id,display_name,geo"}, timeout)
        for inst in data.get("results", []):
            if ((inst.get("geo") or {}).get("city") or "").lower() == city.lower():
                found.append((_tail(inst.get("id")), inst.get("display_name") or ""))
        if page * 200 >= data.get("meta", {}).get("count", 0):
            break
    return found


def openalex_institutions(city: str, *, country: str = "TW", timeout: float = 20.0) -> list[str]:
    """回傳位在指定城市的機構 id。"""
    return [i for i, _ in openalex_city_institutions(city, country=country, timeout=timeout)]


def openalex_authors(topic: str, location: Optional[str], *, limit: int = 5,
                     timeout: float = 20.0) -> Optional[list[dict[str, Any]]]:
    """用主題搜近年論文，挑出所屬機構在指定地點的作者，再批次取作者公開資料。API 失敗回 None。"""
    try:
        filters = ["from_publication_date:2021-01-01"]
        institutions: set[str] = set()
        if location in COUNTRY_CODES:
            filters.append(f"authorships.institutions.country_code:{COUNTRY_CODES[location]}")
        elif location:
            institutions = set(openalex_institutions(location, timeout=timeout))
            if not institutions:
                return []
            filters.append("authorships.institutions.id:" + "|".join(sorted(institutions)[:50]))
        # 論文上的所屬機構是當時的；先多挑幾位，再用作者「目前」所屬機構篩一次
        pool = min(limit * 4, 50)
        works = _openalex("works", {"search": topic, "filter": ",".join(filters), "sort": "cited_by_count:desc",
                                    "per-page": 50, "select": "id,title,doi,publication_year,authorships"}, timeout)
        picked: dict[str, dict[str, Any]] = {}
        for work in works.get("results", []):
            for authorship in work.get("authorships") or []:
                inst_ids = {_tail(i.get("id")) for i in authorship.get("institutions") or []}
                countries = {i.get("country_code") for i in authorship.get("institutions") or []}
                if institutions and not inst_ids & institutions:
                    continue
                if location in COUNTRY_CODES and COUNTRY_CODES[location] not in countries:
                    continue
                author_id = _tail((authorship.get("author") or {}).get("id"))
                if author_id and author_id not in picked:
                    picked[author_id] = {"top_work": {"title": work.get("title") or "", "year": work.get("publication_year"),
                                                      "url": work.get("doi") or work.get("id")}}
                if len(picked) >= pool:
                    break
            if len(picked) >= pool:
                break
        if not picked:
            return []
        details = _openalex("authors", {"filter": "openalex:" + "|".join(picked), "per-page": len(picked),
                                        "select": "id,display_name,orcid,works_count,cited_by_count,"
                                                  "last_known_institutions,topics"}, timeout)
    except (requests.RequestException, ValueError, KeyError):
        return None
    out = []
    for author in details.get("results", []):
        author_id = _tail(author.get("id"))
        current = author.get("last_known_institutions") or []
        if institutions and not {_tail(i.get("id")) for i in current} & institutions:
            continue
        if location in COUNTRY_CODES and COUNTRY_CODES[location] not in {i.get("country_code") for i in current}:
            continue
        # 同時掛好幾個機構時，顯示符合地點的那一個
        local = [i for i in current if (institutions and _tail(i.get("id")) in institutions)
                 or (location in COUNTRY_CODES and i.get("country_code") == COUNTRY_CODES[location])]
        institution = ((local or current or [{}])[0].get("display_name") or "")
        if len(current) > 1:
            institution += f" 等 {len(current)} 個機構"
        out.append({
            "id": author_id,
            "display_name": author.get("display_name") or "",
            "orcid": author.get("orcid") or "",
            "works_count": author.get("works_count"),
            "cited_by_count": author.get("cited_by_count"),
            "institution": institution,
            "topics": [t.get("display_name") for t in (author.get("topics") or [])[:5] if t.get("display_name")],
            **picked.get(author_id, {}),
        })
    order = list(picked)
    return sorted(out, key=lambda a: order.index(a["id"]) if a["id"] in order else len(order))[:limit]


ORCID = "https://pub.orcid.org/v3.0"


def _orcid(path: str, params: Optional[dict[str, Any]] = None, timeout: float = 20.0) -> dict[str, Any]:
    response = requests.get(f"{ORCID}/{path}", params=params, headers={"Accept": "application/json"}, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _split_keywords(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        for part in str(value).replace("；", ";").replace("，", ",").replace(";", ",").split(","):
            part = part.strip()
            if part and part.lower() not in {o.lower() for o in out}:
                out.append(part)
    return out


def orcid_researchers(topics: list[str], location: Optional[str], *, limit: int = 5,
                      timeout: float = 20.0) -> Optional[list[dict[str, Any]]]:
    """ORCID 官方公開 API（不需金鑰）：依研究關鍵字與所屬機構找研究者，再讀每位的公開關鍵字與網站。

    城市用「位在該城市的機構」來篩（機構名單來自 OpenAlex）；國家用機構名稱含國名粗篩。API 失敗回 None。
    """
    terms = [t for t in topics if t] or ["research"]
    quoted = " OR ".join(f'"{t}"' for t in terms)
    parts = [f"(keyword:({quoted}) OR {quoted})"]
    try:
        if location in COUNTRY_CODES:
            parts.append(f'affiliation-org-name:("{location}")')
        elif location:
            names = [n for _, n in openalex_city_institutions(location, timeout=timeout) if n][:25]
            if not names:
                return []
            parts.append("affiliation-org-name:(" + " OR ".join(f'"{n}"' for n in names) + ")")
        data = _orcid("expanded-search/", {"q": " AND ".join(parts), "rows": max(limit * 2, 10)}, timeout)
        out = []
        for row in data.get("expanded-result") or []:
            orcid_id = row.get("orcid-id")
            if not orcid_id:
                continue
            person = _orcid(f"{orcid_id}/person", timeout=timeout)
            keywords = _split_keywords([k.get("content") for k in (person.get("keywords") or {}).get("keyword", [])
                                        if k.get("content")])
            urls = [((u.get("url") or {}).get("value") or "")
                    for u in (person.get("researcher-urls") or {}).get("researcher-url", [])]
            name = " ".join(x for x in (row.get("given-names"), row.get("family-names")) if x)
            out.append({
                "orcid": orcid_id, "name": name or orcid_id,
                "institutions": [i for i in row.get("institution-name") or [] if i][:3],
                "keywords": keywords[:8],
                "biography": ((person.get("biography") or {}).get("content") or "")[:500],
                "urls": [u for u in urls if u][:3],
            })
            if len(out) >= limit:
                break
        return out
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def github_user_count(query: str, *, timeout: float = 10.0) -> Optional[int]:
    """GitHub 官方搜尋 API：這組條件找得到幾個人（不需金鑰，每分鐘 10 次）；失敗回 None。"""
    try:
        r = requests.get("https://api.github.com/search/users", params={"q": query, "per_page": 1},
                         headers={"Accept": "application/vnd.github+json"}, timeout=timeout)
        r.raise_for_status()
        return int(r.json().get("total_count", 0))
    except (requests.RequestException, ValueError, TypeError):
        return None
