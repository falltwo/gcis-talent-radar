"""
每日更新：GCIS 每日設立／解散／變更登記 API → 臺中市的公司事件（與月份清冊同格式）

月份清冊要等下個月才公布，這裡從開始累積的那天起，每次接著上次抓到的那天抓到今天（不往回補更早的日子）：
- 467E8A3A 公司資料設立查詢（Company_Setup_Date eq 某日）
- 561D23B6 公司資料每日解散異動查詢（Change_Of_Approval_Data eq 某日）
- 4347A009 公司資料異動查詢（Change_Of_Approval_Data eq 某日）
這三支只回統編與名稱，所在地與資本額另用 5F64D864（公司登記基本資料-應用一）逐家查：
- 設立、解散：每家都查（全國每天各約 150 家）
- 變更：每天約 700 家，只查「已知在臺中」的公司（月份清冊歷年出現過、稅籍在臺中、或每日資料出現過）；
  從外縣市遷入臺中的變更會漏掉，要等月份清冊補上

輸出 data/raw/gcis_lists/{setup,dissolved,change}/daily/YYYY-MM-DD.csv，欄位與月份清冊相同、只留臺中市、
不留代表人。月份清冊公布後，該月以清冊為準（gcis_registry.load_lists 會略過已有清冊的月份）。

使用量：平臺對系統介接 API 有每日次數上限，正式部署前要依平臺規定送「資料介接使用告知書」登記 IP。
"""
import datetime as dt
import os
import re
import time
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from etl.sources.common import RAW_DATA_DIR, TAICHUNG_DISTRICTS, session

API = "https://data.gcis.nat.gov.tw/od/data/api/{oid}"
DAILY = {  # 種類：(API, 日期欄)
    "setup": ("467E8A3A-72C6-4663-9557-D9D74C597E14", "Company_Setup_Date"),
    "dissolved": ("561D23B6-5EA7-4FF4-A78D-A617ED64BC64", "Change_Of_Approval_Data"),
    "change": ("4347A009-6489-4F19-AC79-78F366BE7976", "Change_Of_Approval_Data"),
}
BASIC = "5F64D864-61CB-4D0D-8AD9-492047CC1EA6"  # 公司登記基本資料-應用一：所在地、資本額、設立日期
COLUMNS = {  # 與月份清冊相同（不含序號、代表人）
    "setup": ["統一編號", "公司名稱", "公司所在地", "資本額", "核准設立日期"],
    "dissolved": ["統一編號", "公司名稱", "公司所在地", "資本額", "核准設立日期", "核准解散日期"],
    "change": ["統一編號", "公司名稱", "公司所在地", "資本額", "核准變更日期"],
}
LISTS = RAW_DATA_DIR / "gcis_lists"
TAICHUNG_ADDRESS = re.compile(r"^[臺台]中市")
DISTRICT_RE = re.compile(r"^[臺台]中市(" + "|".join(TAICHUNG_DISTRICTS) + ")")
REFETCH_DAYS = 3  # 最近幾天每次重抓（當天核准的資料可能晚一點才進 API）


class GcisApiError(RuntimeError):
    """平臺回的是錯誤訊息（例如「非授權介接之IP」「超出本日最大介接次數」），不是資料。"""


class Budget:
    """這次最多呼叫幾次 API；用完就停，下次接續。0 或 None 表示不限。"""

    def __init__(self, max_calls: Optional[int] = None):
        self.max_calls = max_calls or 0
        self.calls = 0

    @property
    def left(self) -> Optional[int]:
        return None if not self.max_calls else max(self.max_calls - self.calls, 0)

    def spend(self) -> None:
        if self.max_calls and self.calls >= self.max_calls:
            raise BudgetExceeded(f"已達本次上限 {self.max_calls} 次")
        self.calls += 1


class BudgetExceeded(RuntimeError):
    pass


def roc_date(day: dt.date) -> str:
    """2026-11-03 → 1151103（民國年 7 碼）"""
    return f"{day.year - 1911:03d}{day.month:02d}{day.day:02d}"


def daily_path(kind: str, day: dt.date) -> Path:
    return LISTS / kind / "daily" / f"{day.isoformat()}.csv"


class Client:
    """呼叫 GCIS API：限速、重試、計次；回應不是 JSON 時當成平臺錯誤訊息。"""

    def __init__(self, budget: Budget, *, rate_per_sec: float = None, get: Callable = None):
        self.budget = budget
        self.delay = 1 / float(rate_per_sec or os.environ.get("GCIS_API_RATE", "2"))
        self._get = get or session().get

    def query(self, oid: str, flt: str, *, skip: int = 0, top: int = 1000) -> list:
        params = {"$format": "json", "$filter": flt, "$skip": skip, "$top": top}
        for attempt in range(3):
            self.budget.spend()
            try:
                r = self._get(API.format(oid=oid), params=params, timeout=60)
            except Exception:
                time.sleep(3 * (attempt + 1))
                continue
            time.sleep(self.delay)
            text = (r.text or "").strip()
            if r.status_code == 200 and not text:
                return []  # 那天沒有資料（假日）
            if r.status_code == 200 and text.startswith("["):
                return r.json()
            if r.status_code == 200:
                raise GcisApiError(text[:120])
            time.sleep(3 * (attempt + 1))
        raise GcisApiError(f"{oid} 連續失敗")

    def day_list(self, kind: str, day: dt.date) -> list[dict]:
        oid, field = DAILY[kind]
        rows, skip = [], 0
        while True:
            page = self.query(oid, f"{field} eq {roc_date(day)}", skip=skip)
            rows += page
            if len(page) < 1000:
                return rows
            skip += 1000

    def basic(self, company_id: str) -> Optional[dict]:
        data = self.query(BASIC, f"Business_Accounting_NO eq {company_id}", top=1)
        return data[0] if data else None


def _capital(rec: dict):
    """清冊的資本額：股份有限公司是實收資本額，有限公司（實收為 0）是資本總額。"""
    paid = rec.get("Paid_In_Capital_Amount") or 0
    return paid or rec.get("Capital_Stock_Amount") or None


def taichung_roster(extra: Optional[pd.DataFrame] = None) -> set[str]:
    """已知在臺中的公司統編：月份清冊與每日資料歷年出現過的，加上稅籍在臺中的。"""
    ids: set[str] = set()
    for path in LISTS.glob("*/**/*.csv"):
        try:
            ids |= set(pd.read_csv(path, dtype=str, usecols=["統一編號"], encoding="utf-8-sig")["統一編號"].dropna())
        except (ValueError, pd.errors.EmptyDataError):
            continue
    tax = RAW_DATA_DIR / "tax_registry" / "bgmopen1_industry.csv"
    if tax.exists():
        try:
            reg = pd.read_csv(tax, dtype=str, usecols=["統一編號", "臺中行政區"], encoding="utf-8-sig")
            ids |= set(reg.loc[reg["臺中行政區"].notna(), "統一編號"])
        except ValueError:
            pass  # 舊版稅籍檔沒有行政區欄
    if extra is not None:
        ids |= set(extra)
    return ids


def fetch_day(client: Client, day: dt.date, roster: set[str]) -> dict[str, list[dict]]:
    """某一天臺中市的設立、解散、變更（與清冊同欄位）。"""
    roc = roc_date(day)
    out: dict[str, list[dict]] = {}
    for kind in DAILY:
        listed = client.day_list(kind, day)
        rows = []
        for item in listed:
            cid = str(item.get("Business_Accounting_NO") or "").strip()
            if not cid or (kind == "change" and cid not in roster):
                continue
            rec = client.basic(cid)
            address = (rec or {}).get("Company_Location") or ""
            if not TAICHUNG_ADDRESS.match(address):
                continue
            row = {"統一編號": cid, "公司名稱": rec.get("Company_Name") or item.get("Company_Name"),
                   "公司所在地": address, "資本額": _capital(rec)}
            if kind == "setup":
                row["核准設立日期"] = roc
            elif kind == "dissolved":
                row["核准設立日期"], row["核准解散日期"] = rec.get("Company_Setup_Date") or "", roc
            else:
                row["核准變更日期"] = roc
            rows.append(row)
            roster.add(cid)
        out[kind] = rows
    return out


def latest_list_month() -> Optional[str]:
    """月份清冊（三種都有）最新的月份，例如 2026-09。"""
    months = [set(p.stem for p in (LISTS / kind).glob("*.csv")) for kind in DAILY]
    common = set.intersection(*months) if all(months) else set()
    return max(common) if common else None


def updated_through() -> Optional[str]:
    """資料更新到哪一天：每日資料最後一個完整的日子（當天抓的還不算）；沒有每日檔就是最新月份清冊的月底。"""
    days = [set(p.stem for p in (LISTS / kind / "daily").glob("*.csv")) for kind in DAILY]
    common = set.intersection(*days) if all(days) else set()
    complete = [d for d in common if coverage(dt.date.fromisoformat(d), dt.date.fromisoformat(d)).get(d) == "daily_api"]
    if complete:
        return max(complete)
    month = latest_list_month()
    if not month:
        return None
    y, m = map(int, month.split("-"))
    return (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()


def coverage(first: dt.date, last: dt.date) -> dict[str, str]:
    """first～last 每一天的資料來源：monthly_list（月份清冊）、daily_api（每日 API，已完整）、
    daily_api_partial（當天抓的，那天還沒結束，隔天重抓才完整）；沒有資料的日子不列。"""
    months = [set(p.stem for p in (LISTS / kind).glob("*.csv")) for kind in DAILY]
    monthly = set.intersection(*months) if all(months) else set()
    out: dict[str, str] = {}
    day = first
    while day <= last:
        paths = [daily_path(kind, day) for kind in DAILY]
        if day.strftime("%Y-%m") in monthly:
            out[day.isoformat()] = "monthly_list"
        elif all(p.exists() for p in paths):
            fetched = min(dt.date.fromtimestamp(p.stat().st_mtime) for p in paths)
            out[day.isoformat()] = "daily_api" if fetched > day else "daily_api_partial"
        day += dt.timedelta(days=1)
    return out


def latest_daily_day() -> Optional[dt.date]:
    """上次抓到哪一天（三種每日檔都有的最後一天）；還沒開始累積回 None。"""
    days = [set(p.stem for p in (LISTS / kind / "daily").glob("*.csv")) for kind in DAILY]
    common = set.intersection(*days) if all(days) else set()
    return dt.date.fromisoformat(max(common)) if common else None


def next_start(today: dt.date, backfill_days: int = 0) -> dt.date:
    """這次從哪天抓：接著上次抓到的那天（那天可能還沒抓完整，重抓一次），還沒開始累積就從今天開始。

    backfill_days > 0 時再往回多抓幾天（手動補資料用）；都不會早於最新月份清冊的下一天。"""
    last = latest_daily_day()
    start = min(last, today) if last else today
    if backfill_days:
        start = min(start, today - dt.timedelta(days=backfill_days))
    return max(start, gap_start(today))


def gap_start(today: dt.date) -> dt.date:
    """要補的第一天：最新月份清冊的下個月 1 號（沒有清冊就從 30 天前開始）。"""
    month = latest_list_month()
    if not month:
        return today - dt.timedelta(days=30)
    y, m = map(int, month.split("-"))
    return dt.date(y + (m == 12), m % 12 + 1, 1)


def fetch_range(start: dt.date, end: dt.date, *, budget: Optional[Budget] = None, client: Optional[Client] = None,
                today: Optional[dt.date] = None, log: Callable[[str], None] = print) -> dict:
    """抓 start～end 每一天（含），寫成每日檔；已抓過的日子跳過（最近 REFETCH_DAYS 天每次重抓）。

    用完次數上限或平臺回錯誤訊息就停下，下次從沒抓完的那天接續。"""
    budget = budget or Budget()
    client = client or Client(budget)
    today = today or dt.date.today()
    roster = taichung_roster()
    done, skipped, stopped = [], 0, ""
    day = start
    while day <= end:
        fresh = (today - day).days <= REFETCH_DAYS
        if not fresh and all(daily_path(kind, day).exists() for kind in DAILY):
            skipped += 1
            day += dt.timedelta(days=1)
            continue
        try:
            result = fetch_day(client, day, roster)
        except (BudgetExceeded, GcisApiError) as exc:
            stopped = f"{day.isoformat()}：{exc}"
            log(f"  停在 {stopped}")
            break
        for kind, rows in result.items():  # 一天三種都抓完才寫檔，中斷時不會留下半天的資料
            path = daily_path(kind, day)
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows, columns=COLUMNS[kind]).to_csv(path, index=False, encoding="utf-8-sig")
        done.append(day.isoformat())
        log(f"  {day.isoformat()}：臺中 設立 {len(result['setup'])}、解散 {len(result['dissolved'])}、"
            f"變更 {len(result['change'])}（累計 API {budget.calls} 次）")
        day += dt.timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat(), "fetched_days": done, "skipped_days": skipped,
            "updated_through": done[-1] if done else None, "api_calls": budget.calls, "stopped": stopped}
