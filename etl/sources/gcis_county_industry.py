"""
F0：GCIS 公司登記家數－按行業別及縣市別（月）
- new       公司登記新設立家數及實收資本額－按行業別及縣市別分   01E5CFC6-…（當月新增）
- dissolved 公司解散、撒銷及廢止家數及實收資本額－按行業別及縣巿別分 795C3F99-…（當月減少）
- existing  公司登記現有家數及實收資本額－按行業別及縣市別        ACA82CEE-…（月底存量）
資本額單位：新台幣百萬元。只取臺中市一列。

輸出 tc_company_by_industry_monthly：year_month × industry × metric
- 2012-06 以前只有孤立的年底月份 → quality_flag=isolated_before_series，建模時排除
- 來源沒有的月份補一列 NaN → quality_flag=missing_at_source（不補 0）
- 與前後 12 個月中位數差距過大 → quality_flag=outlier_candidate（只標記，不刪）
"""
import re

import numpy as np
import pandas as pd

from etl.sources.common import RAW_DATA_DIR, TAICHUNG, fetch, read_csv_bytes, session, write_processed

DATASETS = {
    "new": ("01E5CFC6-9F09-4CB5-BE81-22B451E4B1BD", "公司登記新設立家數及實收資本額－按行業別及縣市別分"),
    "dissolved": ("795C3F99-6AF1-4F96-A944-CEEC36149272", "公司解散、撒銷及廢止家數及實收資本額－按行業別及縣巿別分"),
    "existing": ("ACA82CEE-1C9D-47F8-9E5F-1DE39D5EEAF9", "公司登記現有家數及實收資本額－按行業別及縣市別"),
}
DETAIL = "https://data.gcis.nat.gov.tw/od/detail?oid={oid}"
FILE = "https://data.gcis.nat.gov.tw/od/file?oid={oid}"
ROW = re.compile(r"<td>(\d{4})年(\d{2})月</td>\s*<td[^>]*>\s*<a[^>]*showDialog\('/od/file\?oid=([0-9A-F-]+)'\)", re.S)
SERIES_START = "2012-06"
CORRUPTED = []   # 來源檔損毀的月份


def raw_dir(metric: str):
    # 新設沿用組員已下載的月檔，避免重抓
    if metric == "new":
        return RAW_DATA_DIR / "gcis_new_by_industry_county" / "monthly"
    return RAW_DATA_DIR / f"gcis_{metric}_by_industry_county" / "monthly"


def list_months(s, oid):
    html = s.get(DETAIL.format(oid=oid), timeout=60).text
    seen, out = set(), []
    for y, m, file_oid in ROW.findall(html):   # 頁面由新到舊；同月重複時留第一筆
        ym = f"{y}-{m}"
        if ym not in seen:
            seen.add(ym)
            out.append((ym, file_oid))
    if not out:
        raise RuntimeError(f"{oid} 找不到月份連結，頁面結構可能改了")
    return out


def fetch_all():
    s = session()
    for metric, (oid, title) in DATASETS.items():
        months = list_months(s, oid)
        print(f"[{metric}] {title}：{len(months)} 個月份 {months[-1][0]}～{months[0][0]}")
        for ym, file_oid in months:
            fetch(s, f"gcis_{metric}_by_industry_county", FILE.format(oid=file_oid), raw_dir(metric) / f"{ym}.csv",
                  min_bytes=200)


def _normalize_industry(name: str) -> str:
    return re.sub(r"[；;\s]", "", name)


def _parse(path, metric):
    df = read_csv_bytes(path.read_bytes())
    df.columns = [c.replace(" ", "") for c in df.columns]
    names = df["縣市別"].astype(str).str.strip()
    row = df[names == TAICHUNG]
    if row.empty:
        if names.str.contains("�").any():
            CORRUPTED.append(f"{metric} {path.stem}")   # 來源檔縣市名稱已是亂碼，不用列序硬猜
            return []
        raise ValueError(f"{path.name} 沒有臺中市")
    row = row.iloc[0]
    out = []
    for col in df.columns:
        if col.endswith("家數"):
            ind = col[:-2]
            out.append({"year_month": path.stem, "industry": _normalize_industry(ind), "metric": metric,
                        "companies": pd.to_numeric(row[col], errors="coerce"),
                        "capital_million_twd": pd.to_numeric(row.get(ind + "資本額"), errors="coerce")})
    return out


def _flag_outliers(g: pd.DataFrame) -> pd.Series:
    """與前後各 6 個月的中位數比較，用 MAD 標準化，|z| > 4 標記"""
    v = g["companies"].astype(float)
    med = v.rolling(13, center=True, min_periods=7).median()
    resid = v - med
    mad = (resid.abs()).rolling(37, center=True, min_periods=13).median() * 1.4826
    z = resid / mad.replace(0, np.nan)
    return z.abs() > 4


def transform():
    rows = []
    for metric in DATASETS:
        files = sorted(raw_dir(metric).glob("*.csv"))
        if not files:
            raise FileNotFoundError(f"{raw_dir(metric)} 沒有檔案，請先 fetch")
        for p in files:
            rows += _parse(p, metric)
    df = pd.DataFrame(rows)
    df["quality_flag"] = np.where(df["year_month"] < SERIES_START, "isolated_before_series", "")

    # 補上來源缺的月份（NaN），讓下游看得到缺口
    filled, gaps_note = [], []
    end = df["year_month"].max()
    for (metric, ind), g in df[df["year_month"] >= SERIES_START].groupby(["metric", "industry"]):
        idx = pd.period_range(SERIES_START, end, freq="M").astype(str)
        missing = sorted(set(idx) - set(g["year_month"]))
        if missing:
            filled.append(pd.DataFrame({"year_month": missing, "industry": ind, "metric": metric,
                                        "companies": np.nan, "capital_million_twd": np.nan,
                                        "quality_flag": "missing_at_source"}))
    if filled:
        df = pd.concat([df, *filled], ignore_index=True)
    # 官方月報可作為 GCIS 下載目錄漏月的備援；不做統計插補。
    from etl.sources.moea_company_monthly import URLS, RECOVERY_METRICS, parse_workbook, reconcile_official_gaps
    recovered_months = []
    for ym in URLS:
        workbook = RAW_DATA_DIR / "moea_company_monthly" / f"{ym}.xls"
        if workbook.exists():
            had_gaps = ((df.year_month == ym) & df.companies.isna()).any()
            df = reconcile_official_gaps(df, parse_workbook(workbook, ym, RECOVERY_METRICS[ym]))
            if had_gaps:
                recovered_months.append(ym)
    for metric in DATASETS:
        miss = sorted(df.loc[(df.metric == metric) & (df.quality_flag == "missing_at_source"), "year_month"].unique())
        gaps_note.append(f"{metric} 來源缺月：{miss or '無'}")

    df = df.sort_values(["metric", "industry", "year_month"]).reset_index(drop=True)
    in_series = (df["quality_flag"] == "") & df["companies"].notna()
    for (metric, ind), g in df[in_series].groupby(["metric", "industry"]):
        if metric == "existing":
            continue   # 存量是平滑序列，跳動通常是分類調整，另外看
        flag = _flag_outliers(g)
        df.loc[flag[flag].index, "quality_flag"] = "outlier_candidate"

    out_mfg = df[(df.industry == "製造業") & (df.quality_flag == "outlier_candidate")]
    notes = gaps_note + [
        f"官方經濟部公司登記月報補回：{recovered_months}（official_monthly_recovered，非推估）",
        f"來源檔損毀（縣市名稱為亂碼，當作缺月）：{CORRUPTED or '無'}",
        "2012-06 以前只有孤立年底月份（isolated_before_series），建模排除",
        "行業名稱已去除全形分號與空白（例：公共行政及國防；強制性社會安全 → 公共行政及國防強制性社會安全）",
        f"製造業異常候選：{out_mfg[['metric', 'year_month', 'companies']].to_dict('records')}",
        "資本額單位：新台幣百萬元",
    ]
    write_processed(df, "tc_company_by_industry_monthly",
                    sources=[f"GCIS {t}（oid={o}）" for o, t in DATASETS.values()],
                    grain="臺中市 × 行業大類 × 月 × 指標（new/dissolved/existing）", notes=notes)
    return df


if __name__ == "__main__":
    fetch_all()
    transform()
