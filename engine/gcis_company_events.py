"""臺中市公司事件（每日更新）：最近 N 天的設立、解散、增資，依日期、行政區、產業彙整。

資料來自 gcis_company_events（etl/daily_refresh.py 每天更新）。月份清冊還沒公布的日子是每日 API 的暫時資料，
回傳的 provisional_from 標出從哪一天開始是暫時資料；清冊公布後會以清冊為準重算。
每日 API 只抓最近幾天，清冊公布前沒抓到的日子在 daily 裡是 covered=false（沒有資料，不是 0 家），列在 missing_days。
"""
import datetime as dt
from typing import Any, Dict, Optional

from database.db_manager import db

EVENTS = ("new", "dissolved", "capital_increase")
EVENT_LABEL = {"new": "設立", "dissolved": "解散", "capital_increase": "增資"}
SOURCE = {"name": "經濟部商工行政資料開放平臺：公司設立／解散／變更登記清冊與每日異動 API",
          "url": "https://data.gcis.nat.gov.tw/main/index"}


def _counts(rows, key: str) -> list:
    out: Dict[Any, Dict[str, Any]] = {}
    for r in rows:
        bucket = out.setdefault(r[key], {key: r[key], **{e: 0 for e in EVENTS}})
        bucket[r["event"]] += r["n"]
    return list(out.values())


def get_company_events(days: int = 30, district: Optional[str] = None, section: Optional[str] = None,
                       limit: int = 50) -> Dict[str, Any]:
    try:
        latest = db.fetch_one("SELECT MAX(event_date) AS d, MAX(loaded_at) AS loaded FROM gcis_company_events")
        covered = {r["day"]: r["source"] for r in db.fetch_all("SELECT day, source FROM gcis_event_coverage")}
    except Exception:
        latest, covered = None, {}
    if not latest or not latest["d"]:
        return {"available": False, "error_code": "NO_DATA",
                "message": "尚未載入公司事件資料，請先執行 python -m etl.daily_refresh。"}
    # 期間的最後一天：有資料的最後一天（含當天抓的未完整資料）；舊資料庫沒有涵蓋表時用最後一筆事件
    end = dt.date.fromisoformat(max(covered) if covered else latest["d"])
    start = end - dt.timedelta(days=days - 1)
    complete = [d for d, src in covered.items() if src != "daily_api_partial"]
    where, params = ["event_date BETWEEN ? AND ?"], [start.isoformat(), end.isoformat()]
    if district:
        where.append("district = ?")
        params.append(district)
    if section:
        where.append("industry_section = ?")
        params.append(section.upper())
    cond = " AND ".join(where)
    daily = db.fetch_all(f"SELECT event_date, event, COUNT(*) AS n FROM gcis_company_events WHERE {cond} "
                         "GROUP BY event_date, event ORDER BY event_date", tuple(params))
    by_district = db.fetch_all(f"SELECT COALESCE(district, '未知') AS district, event, COUNT(*) AS n "
                               f"FROM gcis_company_events WHERE {cond} GROUP BY 1, event", tuple(params))
    by_industry = db.fetch_all(f"SELECT COALESCE(industry_section, '?') AS section, "
                               f"COALESCE(MAX(industry_section_name), '未分類') AS name, event, COUNT(*) AS n "
                               f"FROM gcis_company_events WHERE {cond} GROUP BY 1, event", tuple(params))
    events = db.fetch_all(f"SELECT event_date, event, company_id, company_name, district, industry_section, "
                          f"industry_section_name, capital_twd, capital_delta_twd, source FROM gcis_company_events "
                          f"WHERE {cond} ORDER BY event_date DESC, event, company_id LIMIT ?", tuple(params + [limit]))
    provisional = db.fetch_one("SELECT MIN(event_date) AS d FROM gcis_company_events WHERE source = 'daily_api'")
    industries = {}
    for r in by_industry:
        bucket = industries.setdefault(r["section"], {"section": r["section"], "name": r["name"],
                                                       **{e: 0 for e in EVENTS}})
        bucket[r["event"]] += r["n"]
    totals = {e: sum(r["n"] for r in daily if r["event"] == e) for e in EVENTS}
    counts = {d["event_date"]: d for d in _counts(daily, "event_date")}
    series, missing, partial = [], [], []
    day = start
    while day <= end:
        key = day.isoformat()
        src = covered.get(key) if covered else "unknown"
        if src is None:
            missing.append(key)
        elif src == "daily_api_partial":
            partial.append(key)
        row = counts.get(key, {})
        series.append({"date": key, "covered": src is not None, "source": src,
                       **{e: (row.get(e, 0) if src is not None else None) for e in EVENTS}})
        day += dt.timedelta(days=1)
    return {
        "available": True,
        "city": "臺中市",
        "updated_through": max(complete) if complete else end.isoformat(),
        "loaded_at": latest["loaded"],
        "period": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "filters": {"district": district, "section": section.upper() if section else None},
        "provisional_from": provisional["d"] if provisional else None,
        "event_labels": EVENT_LABEL,
        "totals": totals,
        "daily": series,
        "missing_days": missing,
        "partial_days": partial,
        "by_district": sorted(_counts(by_district, "district"), key=lambda r: -r["new"]),
        "by_industry": sorted(industries.values(), key=lambda r: -r["new"]),
        "events": [dict(r) for r in events],
        "source": SOURCE,
        "notes": ["provisional_from 之後是月份清冊公布前的每日 API 暫時資料；清冊公布後以清冊為準",
                  "missing_days 是沒有資料的日子（每日 API 只抓最近幾天，等月份清冊公布補上），不是 0 家；"
                  "partial_days 是當天抓的、還沒結束的日子",
                  "從外縣市遷入臺中的公司，要等月份清冊公布才會出現在增資等變更事件裡",
                  "產業別以稅籍主要行業代號判定，稅籍查無者用第一順位營業項目，可能與官方統計分類不同"],
    }
