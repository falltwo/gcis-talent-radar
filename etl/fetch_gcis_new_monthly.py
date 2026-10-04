"""
下載「公司登記新設立家數及實收資本額－按行業別及縣市別分」所有月份 CSV，
整理成台中市的長表（月份 × 行業大類 × 家數／資本額）。

來源：經濟部商工行政資料開放平臺 oid=01E5CFC6-9F09-4CB5-BE81-22B451E4B1BD
授權：政府資料開放授權條款－第1版
數值是「當月新設」，不是累計。

用法：
    python etl/fetch_gcis_new_monthly.py            # 預設輸出 data/raw/gcis_new_by_industry_county/
    python etl/fetch_gcis_new_monthly.py --county 臺中市
"""
import argparse
import io
import re
import time
from pathlib import Path

import ssl

import pandas as pd
import requests
from requests.adapters import HTTPAdapter


class _GcisTLS(HTTPAdapter):
    """GCIS 的憑證缺 Subject Key Identifier，Python 3.13+ 預設的 VERIFY_X509_STRICT 會拒絕。
    這裡照樣驗證憑證鏈與主機名稱，只關掉 strict 這一項，不是 verify=False。"""

    def init_poolmanager(self, *a, **kw):
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
        kw["ssl_context"] = ctx
        return super().init_poolmanager(*a, **kw)

DETAIL = "https://data.gcis.nat.gov.tw/od/detail?oid=01E5CFC6-9F09-4CB5-BE81-22B451E4B1BD"
FILE = "https://data.gcis.nat.gov.tw/od/file?oid={oid}"
ROW = re.compile(r"<td>(\d{4})年(\d{2})月</td>\s*<td[^>]*>\s*<a[^>]*showDialog\('/od/file\?oid=([0-9A-F-]+)'\)", re.S)


def list_months(session):
    html = session.get(DETAIL, timeout=60).text
    rows = ROW.findall(html)
    if not rows:
        raise RuntimeError("找不到任何月份連結，頁面結構可能改了")
    # 同一個月可能出現兩次（平台曾重傳），保留第一個（頁面由新到舊排列）
    seen, out = set(), []
    for y, m, oid in rows:
        ym = f"{y}-{m}"
        if ym not in seen:
            seen.add(ym)
            out.append((ym, oid))
    return out


def read_csv_bytes(b):
    for enc in ("utf-8-sig", "cp950"):
        try:
            return pd.read_csv(io.BytesIO(b), encoding=enc)
        except Exception:
            continue
    raise ValueError("無法解碼 CSV")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", default="臺中市")
    ap.add_argument("--out", default="data/raw/gcis_new_by_industry_county")
    args = ap.parse_args()

    out = Path(args.out)
    (out / "monthly").mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.mount("https://data.gcis.nat.gov.tw", _GcisTLS())
    s.headers["User-Agent"] = "Mozilla/5.0 (research; gcis-talent-radar)"

    months = list_months(s)
    print(f"共 {len(months)} 個月份：{months[-1][0]} ~ {months[0][0]}")

    frames, failed = [], []
    for ym, oid in months:
        p = out / "monthly" / f"{ym}.csv"
        if not p.exists():
            r = s.get(FILE.format(oid=oid), timeout=60)
            if r.status_code != 200 or len(r.content) < 200:
                failed.append(ym)
                continue
            p.write_bytes(r.content)
            time.sleep(0.5)
        df = read_csv_bytes(p.read_bytes())
        df.columns = [c.replace(" ", "") for c in df.columns]
        row = df[df["縣市別"].astype(str).str.strip() == args.county]
        if row.empty:
            failed.append(ym)
            continue
        row = row.iloc[0]
        for col in df.columns:
            if col.endswith("家數"):
                ind = col[: -len("家數")]
                cap_col = ind + "資本額"
                frames.append({
                    "year_month": ym,
                    "county": args.county,
                    "industry": ind,
                    "new_companies": pd.to_numeric(row[col], errors="coerce"),
                    "new_capital_million_twd": pd.to_numeric(row.get(cap_col), errors="coerce"),
                })

    long = pd.DataFrame(frames).sort_values(["industry", "year_month"])
    dst = out / f"{args.county}_monthly_long.csv"
    long.to_csv(dst, index=False, encoding="utf-8-sig")
    print(f"寫出 {dst}：{len(long)} 列，{long['year_month'].nunique()} 個月")
    # 不能因為頁面有 171 個連結，就假設是連續 171 個月。
    available = set(long["year_month"])
    start, end = pd.Period("2012-06", freq="M"), pd.Period(max(available), freq="M")
    gaps = [str(m) for m in pd.period_range(start, end, freq="M") if str(m) not in available]
    print("2012-06 起的缺月：", gaps)
    if failed:
        print("下載或解析失敗的月份：", failed)


if __name__ == "__main__":
    main()
