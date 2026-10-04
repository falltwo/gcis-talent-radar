from pathlib import Path

import pandas as pd
import pytest

from etl.sources.moea_company_monthly import fill_official_gaps, parse_workbook
from forecast.real_data import load_gcis_mfg_new

ROOT = Path(__file__).resolve().parents[1]


def test_official_recovery_months_and_manufacturing_values():
    for month, expected in (("2025-08", 91), ("2025-09", 75)):
        rows = parse_workbook(ROOT / f"data/raw/moea_company_monthly/{month}.xls", month)
        assert len(rows) == 63
        assert rows.loc[(rows.industry == "製造業") & (rows.metric == "new"), "companies"].item() == expected
    with pytest.raises(ValueError, match="Wrong workbook month"):
        parse_workbook(ROOT / "data/raw/moea_company_monthly/2025-08.xls", "2025-09")


def test_recovery_never_overwrites_observations():
    rows = parse_workbook(ROOT / "data/raw/moea_company_monthly/2025-08.xls", "2025-08")
    with pytest.raises(ValueError, match="Refusing to replace"):
        fill_official_gaps(rows, rows)


def test_latest_gcis_series_is_contiguous_and_observed():
    series = load_gcis_mfg_new()
    assert len(series) == 171
    assert str(series.periods[-1]) == "2026-08"
    assert series.values[list(map(str, series.periods)).index("2025-08")] == 91
    assert series.values[list(map(str, series.periods)).index("2025-09")] == 75
    assert not series.is_estimate


def test_all_company_gaps_are_recovered_with_provenance_flag():
    frame = pd.read_csv(ROOT / "data/processed/tc_company_by_industry_monthly.csv")
    assert frame.companies.notna().all()
    assert frame.capital_million_twd.notna().all()
    assert (frame.quality_flag == "official_monthly_recovered").sum() == 147
    legacy = parse_workbook(ROOT / "data/raw/moea_company_monthly/2014-11.xls", "2014-11", ("existing",))
    assert len(legacy) == 21
