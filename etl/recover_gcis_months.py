"""Offline, reproducible recovery after official monthly workbooks are downloaded."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from etl.sources.moea_company_monthly import URLS, RECOVERY_METRICS, counts_equal, reconcile_official_gaps, parse_workbook

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/moea_company_monthly"
PROCESSED = ROOT / "data/processed/tc_company_by_industry_monthly.csv"


def main():
    frame = pd.read_csv(PROCESSED)
    comparisons = []
    for ym, suffix in (("2025-07", "xlsx"), ("2025-10", "xls")):
        observed = parse_workbook(RAW / f"{ym}.{suffix}", ym)
        joined = frame.merge(observed, on=["year_month", "industry", "metric"])
        if len(joined) != 63 or not counts_equal(joined.companies_x, joined.companies_y):
            raise ValueError(f"Overlapping company counts differ: {ym}")
        if not np.allclose(joined.capital_million_twd_x, joined.capital_million_twd_y, rtol=0, atol=1e-5):
            raise ValueError(f"Overlapping capital differs: {ym}")
        comparisons.append({"month": ym, "matched_rows": 63, "counts_match": True, "capital_match": True})
    controls = parse_workbook(RAW / "2014-11.xls", "2014-11", ("new", "dissolved"))
    joined = frame.merge(controls, on=["year_month", "industry", "metric"])
    if len(joined) != 42 or not counts_equal(joined.companies_x, joined.companies_y):
        raise ValueError("2014-11 new/dissolved controls differ")
    if not np.allclose(joined.capital_million_twd_x, joined.capital_million_twd_y, atol=1e-5, rtol=0):
        raise ValueError("2014-11 control capital differs")
    comparisons.append({"month": "2014-11", "matched_rows": 42, "metrics": ["new", "dissolved"],
                        "counts_match": True, "capital_match": True})
    recovered = pd.concat([parse_workbook(RAW / f"{ym}.xls", ym, RECOVERY_METRICS[ym])
                           for ym in URLS], ignore_index=True)
    # Rerunning is safe: previously recovered values must still match the source.
    repaired = reconcile_official_gaps(frame, recovered)
    if not repaired.equals(frame):
        frame = repaired
        frame.to_csv(PROCESSED, index=False, encoding="utf-8-sig")
    report = {"method": "official_observations_recovered", "is_imputed": False,
              "recovered_rows": len(recovered), "remaining_missing_in_recovered_months": int(
                  frame.loc[frame.year_month.isin(URLS), "companies"].isna().sum()),
              "cross_checks": comparisons,
              "sources": [{"month": ym, "url": url, "file": f"data/raw/moea_company_monthly/{ym}.xls",
                           "sha256": hashlib.sha256((RAW / f"{ym}.xls").read_bytes()).hexdigest()}
                          for ym, url in URLS.items()],
              "industry_aliases_note": "官方月報的營建工程業、出版影音及資通訊業、教育業使用既有資料集名稱作別名對照；不宣稱完整跨期分類不變。"}
    out = ROOT / "reports/forecast_real"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gcis_recovery_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    recovered.to_csv(out / "gcis_recovered_months.csv", index=False, encoding="utf-8-sig")
    catalog_path = ROOT / "data/processed/_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entry = catalog["tc_company_by_industry_monthly"]
    entry["official_recovery"] = report
    entry["notes"] = [n for n in entry["notes"] if not any(s in n for s in ("來源缺月", "目前缺月", "官方月報觀測值補回", "來源檔損毀"))]
    for metric in ("new", "dissolved", "existing"):
        months = sorted(frame.loc[(frame.metric == metric) & frame.companies.isna(), "year_month"].unique())
        entry["notes"].append(f"{metric} 目前缺月：{months or '無'}")
    entry["notes"].append("2014-11 現有家數、2025-08/09：經濟部官方月報觀測值補回，非統計插補；詳見 official_recovery")
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
