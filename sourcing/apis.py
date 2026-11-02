"""網站官方 API：個人頁會跳機器人驗證時改用官方 API 讀公開資料（不繞過驗證）。"""
from __future__ import annotations

from typing import Any, Optional

import requests

STACKEXCHANGE = "https://api.stackexchange.com/2.3"


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


def openalex_institutions(city: str, *, country: str = "TW", timeout: float = 20.0) -> list[str]:
    """回傳位在指定城市的機構 id（例如 Taichung 的中興、東海、逢甲）。"""
    ids: list[str] = []
    for page in range(1, 4):
        data = _openalex("institutions", {"filter": f"country_code:{country}", "per-page": 200, "page": page,
                                          "select": "id,geo"}, timeout)
        for inst in data.get("results", []):
            if ((inst.get("geo") or {}).get("city") or "").lower() == city.lower():
                ids.append(_tail(inst.get("id")))
        if page * 200 >= data.get("meta", {}).get("count", 0):
            break
    return ids


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
