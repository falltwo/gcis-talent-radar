"""Load validated observed monthly series, including official recovered GCIS months.

The pre-gap loader is retained for reproducing the earlier historical run.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from forecast.series import Series

PROCESSED = Path(__file__).resolve().parents[1] / "data" / "processed"


def _monthly_series(frame, period_col, value_col, series_id, name, source):
    frame = frame.sort_values(period_col)
    periods = pd.PeriodIndex(frame[period_col].astype(str), freq="M")
    values = pd.to_numeric(frame[value_col], errors="coerce").to_numpy(float)
    if len(frame) < 37 or np.isnan(values).any() or (values < 0).any():
        raise ValueError(f"{series_id}: insufficient, missing, or negative observations")
    return Series(series_id, name, periods, values, unit="家" if series_id == "tc_mfg_new" else "人",
                  sources=[source])


def load_jobmarket_openings(path=None):
    """Citywide public employment-service new openings, from the 2022 scope."""
    path = Path(path or PROCESSED / "tc_jobmarket_monthly.csv")
    frame = pd.read_csv(path)
    frame = frame[(frame["is_quarter_total"].astype(str).str.lower() == "false")
                  & (frame["scope_period"] == "from_2022")]
    return _monthly_series(frame, "period", "new_openings", "tc_jobmarket_openings",
                           "臺中市公立就業服務系統新登記求才人數",
                           "臺中市就業市場分析季報，月度表；2022 年起同一蒐集範圍")


def load_gcis_mfg_new_pre_gap(path=None):
    """Historical GCIS baseline ending before the 2025-08/09 source gap."""
    path = Path(path or PROCESSED / "tc_company_by_industry_monthly.csv")
    frame = pd.read_csv(path)
    frame = frame[(frame["industry"] == "製造業") & (frame["metric"] == "new")
                  & (frame["year_month"] >= "2012-06") & (frame["year_month"] <= "2025-07")]
    return _monthly_series(frame, "year_month", "companies", "tc_mfg_new",
                           "臺中市製造業新設公司家數（缺月前的歷史段）",
                           "經濟部 GCIS 縣市×行業大類月統計；2025-08/09 缺月未補值")


def load_gcis_mfg_new(path=None):
    """Continuous observed monthly series, including official recovered months."""
    path = Path(path or PROCESSED / "tc_company_by_industry_monthly.csv")
    frame = pd.read_csv(path)
    frame = frame[(frame["industry"] == "製造業") & (frame["metric"] == "new")
                  & (frame["year_month"] >= "2012-06")]
    return _monthly_series(frame, "year_month", "companies", "tc_mfg_new",
                           "臺中市製造業新設公司家數",
                           "GCIS 月統計；2025-08/09 由經濟部官方公司登記月報補回，非插補")
