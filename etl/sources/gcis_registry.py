"""
F1–F3：臺中製造業「行政區 × 中類 × 月」的新設、解散、增資公司數
來源
- GCIS 公司設立／解散／變更登記清冊（月份）AD28285B-… / 4302E583-… / 75353060-…（2013-02 起）
- 財政部 全國營業（稅籍）登記資料 BGMOPEN1（現存營業人，含 6 碼行業代號）
- GCIS API 236EE382（公司登記基本資料-應用三，查營業項目）：給稅籍查不到的公司（多半已解散）
- GCIS API FCB90AB1（營業項目代碼 → 行業標準分類代碼 Dgbas）

規則
- 只取公司所在地為臺中市者，行政區由地址取出
- 產業別：稅籍「行業代號」第一碼（主要行業）前 2 碼；稅籍沒有 → API 第一順位營業項目 → Dgbas 前 2 碼
- 製造業 = 中類 08–34
- 增資：變更清冊的資本額 > 同統編前一次出現（設立或變更清冊）的資本額；第一次出現就是變更的公司無法判斷（不計）
- 個資：清冊的「代表人」、稅籍的營業人名稱與地址都不保留
"""
import io
import json
import re
import time
import zipfile

import numpy as np
import pandas as pd

from etl.sources.common import (RAW_DATA_DIR, TAICHUNG_DISTRICTS, _record, fetch, read_csv_bytes, session,
                                write_processed)

LISTS = {"setup": "AD28285B-7B0E-4241-9F58-F2F0F289333E",
         "dissolved": "4302E583-A7B5-4BE2-A3D6-9707B1AACE1C",
         "change": "75353060-3C3D-453E-8E5C-4ADDEAA8260F"}
DATE_COL = {"setup": "核准設立日期", "dissolved": "核准解散日期", "change": "核准變更日期"}
DETAIL = "https://data.gcis.nat.gov.tw/od/detail?oid={oid}"
FILE = "https://data.gcis.nat.gov.tw/od/file?oid={oid}"
ROW = re.compile(r"<td>(\d{4})年(\d{2})月</td>\s*<td[^>]*>\s*<a[^>]*showDialog\('/od/file\?oid=([0-9A-F-]+)'\)", re.S)
TAX_ZIP = "https://eip.fia.gov.tw/data/BGMOPEN1.zip"
API_COMPANY = "https://data.gcis.nat.gov.tw/od/data/api/236EE382-4942-41A9-BD03-CA0709025E7C?$format=json&$filter=Business_Accounting_NO eq {id}"
API_ITEM = "https://data.gcis.nat.gov.tw/od/data/api/FCB90AB1-E382-45CE-8D4F-394861851E28?$format=json&$filter=Business_Item eq {item}&$skip=0&$top=1"

RAW = RAW_DATA_DIR / "gcis_lists"
TAX = RAW_DATA_DIR / "tax_registry"
CACHE_COMPANY = RAW_DATA_DIR / "gcis_api_cache" / "company_items.jsonl"
CACHE_ITEM = RAW_DATA_DIR / "gcis_api_cache" / "item_dgbas.json"
MFG = {f"{i:02d}" for i in range(8, 35)}
DISTRICT_RE = re.compile(r"^[臺台]中市(" + "|".join(TAICHUNG_DISTRICTS) + ")")


# ------------------------------------------------------------------ 下載
def fetch_lists():
    """清冊只留臺中市的列、刪除代表人後存檔（manifest 記錄原檔的雜湊）"""
    s = session()
    for kind, oid in LISTS.items():
        html = s.get(DETAIL.format(oid=oid), timeout=60).text
        months, seen = [], set()
        for y, m, f in ROW.findall(html):
            if f"{y}-{m}" not in seen:
                seen.add(f"{y}-{m}")
                months.append((f"{y}-{m}", f))
        print(f"[{kind}] {len(months)} 個月份")
        for ym, f in months:
            dest = RAW / kind / f"{ym}.csv"
            if dest.exists():
                continue
            r = s.get(FILE.format(oid=f), timeout=180)
            if r.status_code != 200 or len(r.content) < 100:
                print(f"  ✗ {kind} {ym} HTTP {r.status_code}")
                continue
            df = read_csv_bytes(r.content, dtype=str)
            df = df[df["公司所在地"].str.match(r"^[臺台]中市", na=False)].drop(columns=["代表人"], errors="ignore")
            dest.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(dest, index=False, encoding="utf-8-sig")
            _record(f"gcis_list_{kind}", FILE.format(oid=f), dest, r.content)
            time.sleep(0.3)


def fetch_tax_registry():
    """稅籍檔 300 MB：只留統編、行業代號、設立日期（不留名稱、地址）"""
    dest = TAX / "bgmopen1_industry.csv"
    if dest.exists():
        return
    s = session()
    r = s.get(TAX_ZIP, timeout=600)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        df = pd.read_csv(z.open(name), dtype=str, skiprows=[1], encoding="utf-8-sig",
                         usecols=["統一編號", "總機構統一編號", "設立日期", "行業代號", "行業代號1", "行業代號2", "行業代號3"])
    df = df.dropna(subset=["統一編號"])
    TAX.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False, encoding="utf-8-sig")
    _record("tax_registry", TAX_ZIP, dest, r.content)
    print(f"  稅籍：{len(df):,} 筆")


def _load_cache():
    done = {}
    if CACHE_COMPANY.exists():
        for line in CACHE_COMPANY.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done[r["id"]] = r
    return done


def fetch_api(ids_newest_first, rate_per_sec: float = 2.0, limit: int = None):
    """逐筆查營業項目，結果附加到 jsonl 快取；可隨時中斷、重跑會接續"""
    s = session()
    done = _load_cache()
    todo = [i for i in ids_newest_first if i not in done][:limit]
    print(f"  API 待查 {len(todo):,} 家（已快取 {len(done):,}）")
    CACHE_COMPANY.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_COMPANY.open("a", encoding="utf-8") as f:
        for n, cid in enumerate(todo, 1):
            try:
                r = s.get(API_COMPANY.format(id=cid), timeout=30)
                data = r.json() if r.status_code == 200 and r.text.strip() else []
            except Exception as e:
                print(f"    {cid} 失敗：{e!r}")
                time.sleep(5)
                continue
            rec = {"id": cid, "found": bool(data)}
            if data:
                items = sorted(data[0].get("Cmp_Business") or [], key=lambda b: b.get("Business_Seq_NO", ""))
                rec.update(status=data[0].get("Company_Status_Desc"), items=[b["Business_Item"] for b in items][:5])
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if n % 500 == 0:
                f.flush()
                print(f"    {n:,}/{len(todo):,}")
            time.sleep(1 / rate_per_sec)


def fetch_item_dgbas(items):
    """營業項目代碼 → 行業標準分類代碼（Dgbas 欄可能列多個 4 碼）"""
    s = session()
    cache = json.loads(CACHE_ITEM.read_text(encoding="utf-8")) if CACHE_ITEM.exists() else {}
    for item in sorted(set(items) - set(cache)):
        try:
            data = s.get(API_ITEM.format(item=item), timeout=30).json()
        except Exception:
            continue
        codes = re.findall(r"(?m)^\s*(\d{4})", data[0].get("Dgbas") or "") if data else []
        cache[item] = codes
        time.sleep(0.3)
    CACHE_ITEM.parent.mkdir(parents=True, exist_ok=True)
    CACHE_ITEM.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    return cache


# ------------------------------------------------------------------ 整理
def load_lists():
    frames = []
    for kind in LISTS:
        for p in sorted((RAW / kind).glob("*.csv")):
            d = pd.read_csv(p, dtype=str, encoding="utf-8-sig")
            d = d.rename(columns={"統一編號": "company_id", "公司所在地": "address", "資本額": "capital",
                                  DATE_COL[kind]: "event_date"})
            d["kind"], d["list_month"] = kind, p.stem
            frames.append(d[["company_id", "address", "capital", "event_date", "kind", "list_month"]])
    df = pd.concat(frames, ignore_index=True)
    df["capital"] = pd.to_numeric(df["capital"], errors="coerce")
    roc = df["event_date"].str.zfill(7)
    df["event_month"] = (roc.str[:3].astype(float) + 1911).astype("Int64").astype(str) + "-" + roc.str[3:5]
    df["district"] = df["address"].str.extract(DISTRICT_RE)[0]
    return df


def ids_needing_api(df):
    tax = pd.read_csv(TAX / "bgmopen1_industry.csv", dtype=str, usecols=["統一編號"])
    known = set(tax["統一編號"])
    sub = df[df.kind.isin(["setup", "dissolved"])].sort_values("list_month", ascending=False)
    return [i for i in sub["company_id"].drop_duplicates() if i not in known]


def classify(df):
    tax = pd.read_csv(TAX / "bgmopen1_industry.csv", dtype=str).drop_duplicates("統一編號")
    code = dict(zip(tax["統一編號"], tax["行業代號"].fillna("").str[:2]))
    cache = _load_cache()
    item_map = json.loads(CACHE_ITEM.read_text(encoding="utf-8")) if CACHE_ITEM.exists() else {}
    ind, src = [], []
    for cid in df["company_id"]:
        if code.get(cid):
            ind.append(code[cid]); src.append("tax_registry")
            continue
        rec = cache.get(cid)
        if rec and rec.get("items"):
            dg = item_map.get(rec["items"][0], [])
            ind.append(dg[0][:2] if dg else None); src.append("gcis_api_item" if dg else "item_unmapped")
        else:
            ind.append(None); src.append("api_not_found" if rec else "unclassified")
    return pd.Series(ind, index=df.index), pd.Series(src, index=df.index)


def transform():
    df = load_lists()
    df["industry_code"], df["industry_source"] = classify(df)

    # 增資：同統編依日期排序，資本額比前一筆高
    df = df.sort_values(["company_id", "event_date", "kind"])
    df["prev_capital"] = df.groupby("company_id")["capital"].shift()
    df["capital_increase"] = (df.kind == "change") & df.prev_capital.notna() & (df.capital > df.prev_capital)
    df["capital_delta"] = np.where(df.capital_increase, df.capital - df.prev_capital, np.nan)

    events = pd.concat([
        df[df.kind == "setup"].assign(event="new"),
        df[df.kind == "dissolved"].assign(event="dissolved"),
        df[df.capital_increase].assign(event="capital_increase"),
    ])
    events["is_manufacturing"] = events["industry_code"].isin(MFG)

    # 每月分類涵蓋率（所有臺中事件中，已知產業別的比例）
    cov = events.groupby(["event", "event_month"]).agg(
        events=("company_id", "size"), classified=("industry_code", lambda s: s.notna().sum())).reset_index()
    cov["classified_share"] = cov["classified"] / cov["events"]

    # 解散公司幾乎都不在稅籍（只收現存營業人），API 補查完成前判定率接近 0，放進來會誤導成「沒有退場」
    low = cov[(cov.event == "dissolved") & (cov.classified_share < 0.8)]["event_month"]
    mfg = events[events.is_manufacturing & ~((events.event == "dissolved") & events.event_month.isin(low))]
    out = mfg.groupby(["event_month", "district", "industry_code", "event"], dropna=False).agg(
        companies=("company_id", "nunique"), capital_twd=("capital", "sum"),
        capital_delta_twd=("capital_delta", "sum")).reset_index().rename(columns={"event_month": "year_month"})
    out = out.merge(cov.rename(columns={"event_month": "year_month"})[["event", "year_month", "classified_share"]],
                    on=["event", "year_month"], how="left")
    write_processed(out, "tc_mfg_company_events_monthly",
                    sources=["GCIS 公司設立／解散／變更登記清冊（月份）", "財政部 全國營業（稅籍）登記資料 BGMOPEN1",
                             "GCIS API 236EE382（營業項目）、FCB90AB1（營業項目→行業代碼）"],
                    grain="臺中市行政區 × 製造業中類 × 月 × 事件（new／dissolved／capital_increase）",
                    notes=["⚠ 產業別定義與 GCIS 官方統計不同：本表以稅籍『主要行業代號』判定（實際以製造業報稅者），"
                           "2026-08 臺中製造業新設本表約 20 家，官方統計 75 家；以營業項目判定則『第一項為製造』45 家、"
                           "『任一項為製造』102 家。官方分類規則無法由公開資料重現。全市趨勢請用 tc_company_by_industry_monthly",
                           "解散事件：判定率 < 80% 的月份不列入（解散公司不在稅籍，需 API 補查）",
                           "事件月份以核准日期為準，不是清冊月份",
                           "classified_share：該月臺中所有同類事件中已判定產業別的比例，偏低的月份中類數字會低估",
                           "增資只計算前一筆資本額已知者；2013 年前設立且之後第一次出現就是變更的公司，第一次不計",
                           "產業別依稅籍主要行業代號；稅籍查無者用第一順位營業項目轉換，精度較低（industry_source）"])
    write_processed(cov, "tc_company_events_coverage_monthly", sources=["同上"],
                    grain="月 × 事件：臺中全部事件數與已判定產業別比例",
                    notes=["用來判斷 tc_mfg_company_events_monthly 各月可信度"])
    return out


if __name__ == "__main__":
    fetch_lists()
    fetch_tax_registry()
