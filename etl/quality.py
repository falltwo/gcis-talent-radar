"""
資料品質檢查：讀 data/processed/_catalog.json 與各表，寫出 reports/DATA_QUALITY.md
檢查項目
1. 沒有個資欄位
2. 主鍵不重複
3. 缺值數量（缺值是保留下來的，不是錯誤，但要看得到）
4. 各表的專屬檢查（缺月、交叉核對、涵蓋率）
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PROCESSED_DATA_DIR, REPORT_DIR
from etl.sources.common import CATALOG, PII_PATTERN

KEYS = {
    "tc_company_by_industry_monthly": ["year_month", "industry", "metric"],
    "tc_jobmarket_monthly": ["period"],
    "tc_jobmarket_occupation_q": ["roc_year", "quarter", "occupation"],
    "tc_jobmarket_industry_q": ["roc_year", "quarter", "industry"],
    "tc_factory_district_industry_annual": ["roc_year", "district", "industry_code"],
    "tc_factory_count_district_monthly": ["year_month", "district", "industry"],
    "tc_factory_survey_city_annual": ["year", "industry"],
    "tc_labor_insurance_annual": ["year_month", "industry_code", "unit_type_code", "employment_insurance_flag"],
    "tc_vocational_dept_annual": None,   # 同校同科可能有多個日夜別／等級列，不設主鍵
    "tc_udb_dept_annual": ["academic_year", "school", "dept_code", "dept", "program"],
    "tc_taiwanjobs_snapshot": ["snapshot_date", "url"],
    "tc_mfg_company_events_monthly": ["year_month", "district", "industry_code", "event"],
    "tc_company_events_coverage_monthly": ["event", "event_month"],
}


def _read(name):
    return pd.read_csv(PROCESSED_DATA_DIR / f"{name}.csv", dtype={"industry_code": str}, low_memory=False)


def _specific(name, df):
    out = []
    if name == "tc_company_by_industry_monthly":
        mfg = df[(df.industry == "製造業") & (df.quality_flag != "isolated_before_series")]
        for metric, g in mfg.groupby("metric"):
            zero_filled = ((g.quality_flag == "missing_at_source") & g.companies.notna()).sum()
            out.append(f"製造業 {metric}：{g.companies.notna().sum()} 期有值、{g.companies.isna().sum()} 期缺值"
                       f"（缺值被補成數字的筆數 {zero_filled}，應為 0）")
    elif name == "tc_jobmarket_monthly":
        m = df[~df.is_quarter_total]
        rng = pd.period_range(m.period.min(), m.period.max(), freq="M").astype(str)
        out.append(f"月資料 {m.period.min()}～{m.period.max()}，缺月 {sorted(set(rng) - set(m.period)) or '無'}")
    elif name == "tc_factory_district_industry_annual":
        out.append(f"{df.district.nunique()} 區 × {df.industry_code.nunique()} 中類 × {df.roc_year.nunique()} 年")
        city = PROCESSED_DATA_DIR / "tc_factory_survey_city_annual.csv"
        if city.exists():
            s = pd.read_csv(city)
            s["industry"] = s["industry"].str.replace("製造業$", "業", regex=True)
            for roc in sorted(df.roc_year.unique())[-3:]:
                y = df[df.roc_year == roc].groupby("industry")[["factories", "employees"]].sum()
                c = s[s.year == roc + 1911].set_index("industry")[["factories", "employees"]]
                j = y.join(c, rsuffix="_city", how="inner")
                if len(j):
                    out.append(f"{roc} 年各區加總 vs 全市調查：家數差 {int((j.factories - j.factories_city).sum())}，"
                               f"員工少 {(1 - j.employees.sum() / j.employees_city.sum()) * 100:.2f}%（未滿 4 家保密格）")
        sup = (df.employees_flag == "suppressed_lt4").mean() * 100
        out.append(f"員工數保密格占 {sup:.1f}%")
    elif name == "tc_labor_insurance_annual":
        e = df[(df.industry_code == "C") & df.employee_scope].groupby("year_month")["insured"].sum()
        out.append("臺中製造業受僱者（12 月）：" + "、".join(f"{k} {int(v):,}" for k, v in e.items()))
    elif name == "tc_taiwanjobs_snapshot":
        out.append(f"快照 {df.snapshot_date.nunique()} 天：{sorted(df.snapshot_date.unique())}")
    elif name == "tc_company_events_coverage_monthly":
        for ev, g in df[df.event_month >= "2013-02"].groupby("event"):
            out.append(f"{ev}：產業別判定率中位數 {g.classified_share.median():.0%}，最低 {g.classified_share.min():.0%}")
    return out


def write_quality_report() -> Path:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() else {}
    lines = [f"# 資料品質報告", "", f"產生時間：{dt.datetime.now():%Y-%m-%d %H:%M}（`python -m etl.run_real_etl` 自動產生）", ""]
    summary = []
    for name, meta in catalog.items():
        df = _read(name)
        pii = [c for c in df.columns if PII_PATTERN.search(str(c))]
        key = KEYS.get(name)
        dup = int(df.duplicated(key).sum()) if key else None
        na = df.isna().sum()
        status = "✅" if not pii and not dup else "❌"
        summary.append(f"| {status} | `{name}` | {len(df):,} | {meta['grain']} | {'無' if not pii else pii} | "
                       f"{'—' if dup is None else dup} |")
        lines += [f"## `{name}`", "", f"- 粒度：{meta['grain']}", f"- 來源：{'；'.join(meta['sources'])}",
                  f"- 列數：{len(df):,}", f"- 缺值欄位：" + ("、".join(f"{c} {n:,}" for c, n in na[na > 0].items()) or "無")]
        lines += [f"- {x}" for x in _specific(name, df)]
        lines += [f"- 註記：{n}" for n in meta.get("notes", [])] + [""]
    header = ["## 總覽", "", "| 狀態 | 表 | 列數 | 粒度 | 個資欄位 | 主鍵重複 |", "|---|---|---|---|---|---|"]
    lines[4:4] = header + summary + [""]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "DATA_QUALITY.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_quality_report())
