"""
每日更新經濟部商工資料（可排程每天跑一次；中斷後重跑會接續）

    python -m etl.daily_refresh                  # 全部步驟
    python -m etl.daily_refresh --max-calls 3000 # 這次最多呼叫 GCIS API 幾次（預設 GCIS_DAILY_MAX_CALLS 或 3000；0 = 不限）
    python -m etl.daily_refresh --skip-tax       # 不重新下載稅籍檔（300 MB，預設 30 天更新一次）
    python -m etl.daily_refresh --backfill-days 7 # 手動往回多抓幾天（預設 0：從上次抓到的那天接著抓，第一次只抓今天）

自動每天跑：Windows 用 scripts/register_daily_refresh_task.ps1 登記工作排程器；Linux／macOS 用 cron 跑
scripts/daily_refresh.sh；伺服器設 GCIS_DAILY_REFRESH=1 則由 etl/scheduler.py 在背景排程。三種共用鎖檔，不會重複跑。

步驟（一步失敗不影響其他步驟，結果寫在 data/processed/_daily_refresh.json）：
1. 月報統計：公司登記新設立家數（按行業別及縣市別）有新月份就下載，重新載入資料庫 gcis_new_company_monthly；
   新設／解散／現有家數的長表 tc_company_by_industry_monthly 一起更新
2. 月份清冊：公司設立／解散／變更登記清冊有新月份就下載
3. 稅籍檔：超過 30 天就重新下載（判斷產業別、哪些公司在臺中）
4. 每日 API：從上次抓到的那天接著抓到今天，臺中市的設立、解散、變更（etl/sources/gcis_daily.py）。
   第一次執行只抓今天，不往回補：開始累積之前的日子在 API 標成沒有資料（不是 0 家），月份清冊公布後由清冊補上
5. 營業項目：每日資料裡稅籍查不到的公司（多半是剛設立的）用 API 查營業項目，判斷產業別
6. 整理：重算 tc_mfg_company_events_monthly，並把最近 24 個月的事件載入資料庫 gcis_company_events
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BASE_DIR  # noqa: E402
from database.db_manager import db  # noqa: E402

LOG_PATH = BASE_DIR / "data" / "processed" / "_daily_refresh.json"
KEEP_MONTHS = 24
SOURCE_URL = "https://data.gcis.nat.gov.tw/od/data/api/"
# 行業標準分類：中類前 2 碼 → 大類
SECTIONS = [("A", "農、林、漁、牧業", 1, 3), ("B", "礦業及土石採取業", 5, 6), ("C", "製造業", 8, 34),
            ("D", "電力及燃氣供應業", 35, 35), ("E", "用水供應及污染整治業", 36, 39), ("F", "營建工程業", 41, 43),
            ("G", "批發及零售業", 45, 48), ("H", "運輸及倉儲業", 49, 54), ("I", "住宿及餐飲業", 55, 56),
            ("J", "出版影音及資通訊業", 58, 63), ("K", "金融及保險業", 64, 66), ("L", "不動產業", 67, 68),
            ("M", "專業、科學及技術服務業", 69, 76), ("N", "支援服務業", 77, 82), ("O", "公共行政及國防", 83, 84),
            ("P", "教育業", 85, 85), ("Q", "醫療保健及社會工作服務業", 86, 88), ("R", "藝術、娛樂及休閒服務業", 90, 93),
            ("S", "其他服務業", 94, 96)]


def industry_section(code) -> tuple:
    """中類 2 碼 → (大類代碼, 大類名稱)；無法判斷回 (None, None)。"""
    try:
        n = int(str(code)[:2])
    except (TypeError, ValueError):
        return None, None
    return next(((s, name) for s, name, lo, hi in SECTIONS if lo <= n <= hi), (None, None))


def load_company_events(events, *, keep_months: int = KEEP_MONTHS, today: Optional[dt.date] = None) -> dict:
    """把事件載入資料庫 gcis_company_events（只留最近 keep_months 個月，資料庫才不會越來越大）。"""
    import pandas as pd

    today = today or dt.date.today()
    first = (pd.Timestamp(today) - pd.DateOffset(months=keep_months)).strftime("%Y-%m-01")
    recent = events[events["event_day"] >= first].copy()
    loaded_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    rows = []
    for r in recent.itertuples(index=False):
        section, section_name = industry_section(r.industry_code)
        district = r.district if isinstance(r.district, str) else None
        rows.append((r.event_day, r.event, r.company_id, r.company_name if isinstance(r.company_name, str) else None,
                     district, r.industry_code if isinstance(r.industry_code, str) else None, section, section_name,
                     r.industry_source, None if pd.isna(r.capital) else float(r.capital),
                     None if pd.isna(r.capital_delta) else float(r.capital_delta), r.source, loaded_at))
    db.init_db()
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM gcis_company_events")
        conn.executemany("""INSERT OR REPLACE INTO gcis_company_events (
            event_date, event, company_id, company_name, district, industry_code, industry_section,
            industry_section_name, industry_source, capital_twd, capital_delta_twd, source, loaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
        conn.commit()
    finally:
        conn.close()
    return {"table": "gcis_company_events", "rows": len(rows), "from": first,
            "through": recent["event_day"].max() if len(recent) else None,
            "daily_api_rows": int((recent["source"] == "daily_api").sum())}


def _monthly_statistics() -> dict:
    from etl import fetch_gcis_new_monthly
    from etl.load_official_labor_market import load_gcis_new_company_monthly
    from etl.sources import gcis_county_industry

    fetch_gcis_new_monthly.main([])
    result = load_gcis_new_company_monthly()
    gcis_county_industry.fetch_all()
    gcis_county_industry.transform()
    return result


def _monthly_lists() -> dict:
    from etl.sources import gcis_daily, gcis_registry

    gcis_registry.fetch_lists()
    return {"latest_month": gcis_daily.latest_list_month()}


def _tax_registry(skip: bool) -> dict:
    from etl.sources import gcis_registry

    if skip:
        return {"skipped": True}
    fresh = gcis_registry.tax_registry_fresh()
    gcis_registry.fetch_tax_registry()
    return {"downloaded": not fresh}


def _daily_api(budget, today: dt.date, backfill_days: int) -> dict:
    from etl.sources import gcis_daily

    return gcis_daily.fetch_range(gcis_daily.next_start(today, backfill_days), today, budget=budget, today=today)


def _business_items(budget) -> dict:
    from etl.sources import gcis_registry

    if budget.left == 0:
        return {"skipped": "本次 API 次數已用完"}
    # 只查每日資料裡的公司；歷年清冊的公司不在這裡補查（要補請用 python -m etl.run_real_etl --api-limit N）
    lists = gcis_registry.load_lists()
    ids = gcis_registry.ids_needing_api(lists[lists["source"] == "daily_api"])
    gcis_registry.fetch_api(ids, limit=budget.left)
    items = [i for r in gcis_registry._load_cache().values() for i in r.get("items", [])[:1]]
    gcis_registry.fetch_item_dgbas(items)
    return {"pending_before": len(ids)}


def load_coverage(*, keep_months: int = KEEP_MONTHS, today: Optional[dt.date] = None) -> dict:
    """哪些日子有資料（gcis_event_coverage），API 才分得出「那天 0 家」和「那天沒有資料」。"""
    import pandas as pd
    from etl.sources import gcis_daily

    today = today or dt.date.today()
    first = (pd.Timestamp(today) - pd.DateOffset(months=keep_months)).replace(day=1).date()
    days = gcis_daily.coverage(first, today)
    db.init_db()
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM gcis_event_coverage")
        conn.executemany("INSERT INTO gcis_event_coverage (day, source) VALUES (?, ?)", sorted(days.items()))
        conn.commit()
    finally:
        conn.close()
    return {"covered_days": len(days), "partial_days": [d for d, s in days.items() if s == "daily_api_partial"]}


def _rebuild(today: dt.date) -> dict:
    from etl.sources import gcis_registry

    gcis_registry.transform()
    return {**load_company_events(gcis_registry.build_events(), today=today), **load_coverage(today=today)}


def run(*, max_calls: Optional[int] = None, skip_tax: bool = False, today: Optional[dt.date] = None,
        backfill_days: Optional[int] = None,
        steps: Optional[dict[str, Callable[[], dict]]] = None, log: Callable[[str], None] = print) -> dict:
    """跑一次每日更新，回傳（並寫入 _daily_refresh.json）每一步的結果。"""
    from etl.sources.gcis_daily import Budget

    today = today or dt.date.today()
    if max_calls is None:
        max_calls = int(os.environ.get("GCIS_DAILY_MAX_CALLS", "3000"))
    budget = Budget(max_calls)
    if backfill_days is None:
        backfill_days = int(os.environ.get("GCIS_DAILY_BACKFILL_DAYS", "0"))
    steps = steps or {
        "monthly_statistics": _monthly_statistics,
        "monthly_lists": _monthly_lists,
        "tax_registry": lambda: _tax_registry(skip_tax),
        "daily_api": lambda: _daily_api(budget, today, backfill_days),
        "business_items": lambda: _business_items(budget),
        "rebuild": lambda: _rebuild(today),
    }
    report = {"started_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "steps": {}}
    for name, fn in steps.items():
        log(f"\n=== {name} ===")
        t = time.time()
        try:
            report["steps"][name] = {"ok": True, "seconds": round(time.time() - t), **(fn() or {})}
            report["steps"][name]["seconds"] = round(time.time() - t)
        except Exception as exc:  # 一步失敗不影響其他步驟
            traceback.print_exc()
            report["steps"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300],
                                     "seconds": round(time.time() - t)}
    report["finished_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    report["api_calls"] = budget.calls
    report["ok"] = all(s["ok"] for s in report["steps"].values())
    from etl.sources.gcis_daily import updated_through
    report["updated_through"] = updated_through()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def last_report() -> dict:
    try:
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="每日更新經濟部商工資料")
    ap.add_argument("--max-calls", type=int, default=None, help="這次最多呼叫 GCIS API 幾次（0 = 不限）")
    ap.add_argument("--skip-tax", action="store_true", help="不重新下載稅籍檔")
    ap.add_argument("--backfill-days", type=int, default=None, help="手動往回多抓幾天（預設 0：從上次抓到的那天接著抓）")
    args = ap.parse_args(argv)
    from etl import scheduler

    if not scheduler.acquire_lock():  # 系統排程與伺服器內建排程可能同時觸發，只跑一個
        print("另一個每日更新正在執行，這次略過。")
        sys.exit(0)
    try:
        report = run(max_calls=args.max_calls, skip_tax=args.skip_tax, backfill_days=args.backfill_days)
    finally:
        scheduler.release_lock()
    print(json.dumps({k: v for k, v in report.items() if k != "steps"}, ensure_ascii=False))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
