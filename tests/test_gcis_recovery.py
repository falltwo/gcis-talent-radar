from pathlib import Path

import pandas as pd
import pytest

from etl.sources.moea_company_monthly import fill_official_gaps, parse_workbook
from forecast.real_data import load_gcis_mfg_new
from etl import recover_gcis_months
from etl.sources import gcis_county_industry as gcis
from etl.sources.moea_company_monthly import counts_equal

ROOT = Path(__file__).resolve().parents[1]


def mock_raw_rows(frame, tmp_path, monkeypatch):
    for metric in gcis.DATASETS:
        directory = tmp_path / metric
        directory.mkdir()
        for month in frame.year_month.unique():
            (directory / f"{month}.csv").touch()
    monkeypatch.setattr(gcis, "raw_dir", lambda metric: tmp_path / metric)
    monkeypatch.setattr(gcis, "_parse", lambda p, metric:
                        frame[(frame.metric == metric) & (frame.year_month == p.stem)].to_dict("records"))


@pytest.mark.parametrize("scope", ["single", "metric", "month", "none"])
def test_main_etl_recovers_partial_gaps_without_changing_observations(tmp_path, monkeypatch, scope):
    frame = pd.read_csv(ROOT / "data/processed/tc_company_by_industry_monthly.csv")
    mask = frame.year_month.eq("2025-08")
    if scope in ("single", "metric"):
        mask &= frame.metric.eq("new")
    if scope == "single":
        mask &= frame.industry.eq("製造業")
    if scope == "none":
        mask &= False
    partial = frame.copy()
    partial.loc[mask, "companies"] = float("nan")
    # Keep capital intact to ensure recovery never replaces known capital.
    partial.loc[mask, "quality_flag"] = "missing_at_source"
    mock_raw_rows(partial, tmp_path, monkeypatch)
    monkeypatch.setattr(gcis, "write_processed", lambda *args, **kwargs: None)
    actual = gcis.transform().set_index(["year_month", "industry", "metric"]).sort_index()
    expected = frame.set_index(["year_month", "industry", "metric"]).sort_index()
    pd.testing.assert_frame_equal(actual[["companies", "capital_million_twd"]],
                                  expected[["companies", "capital_million_twd"]], check_dtype=False, check_exact=True)
    repaired_keys = pd.MultiIndex.from_frame(frame.loc[mask, ["year_month", "industry", "metric"]])
    assert (actual.loc[repaired_keys, "quality_flag"] == "official_monthly_recovered").all()
    assert actual.loc[("2025-08", "製造業", "new"), "companies"] == 91


def test_main_etl_rejects_conflicting_overlap_before_write(tmp_path, monkeypatch):
    frame = pd.read_csv(ROOT / "data/processed/tc_company_by_industry_monthly.csv")
    frame.loc[(frame.year_month == "2025-08") & (frame.industry == "製造業") & (frame.metric == "new"), "companies"] = float("nan")
    frame.loc[(frame.year_month == "2025-08") & (frame.industry == "總計") & (frame.metric == "existing"), "companies"] += 1
    mock_raw_rows(frame, tmp_path, monkeypatch)
    writes = []
    monkeypatch.setattr(gcis, "write_processed", lambda *args, **kwargs: writes.append(args))
    with pytest.raises(ValueError, match="contradictory"):
        gcis.transform()
    assert not writes


@pytest.mark.parametrize("month,metric", [("2025-08", "existing"), ("2025-07", "existing"),
                                          ("2025-10", "existing"), ("2014-11", "new")])
@pytest.mark.parametrize("delta", [-1, 1])
def test_repair_rejects_one_company_conflict_without_writes(tmp_path, monkeypatch, month, metric, delta):
    import shutil
    processed = tmp_path / "data/processed"
    processed.mkdir(parents=True)
    target = processed / "tc_company_by_industry_monthly.csv"
    frame = pd.read_csv(recover_gcis_months.PROCESSED)
    frame.loc[(frame.year_month == month) & (frame.industry == "總計") & (frame.metric == metric), "companies"] += delta
    frame.to_csv(target, index=False)
    catalog = processed / "_catalog.json"
    shutil.copyfile(ROOT / "data/processed/_catalog.json", catalog)
    before = {p: p.read_bytes() for p in (target, catalog)}
    monkeypatch.setattr(recover_gcis_months, "ROOT", tmp_path)
    monkeypatch.setattr(recover_gcis_months, "PROCESSED", target)
    with pytest.raises(ValueError):
        recover_gcis_months.main()
    assert all(p.read_bytes() == content for p, content in before.items())
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize("value", [-1, 1.5, float("inf"), float("nan")])
def test_counts_must_be_finite_nonnegative_integers(value):
    with pytest.raises(ValueError, match="finite nonnegative integers"):
        counts_equal([value], [value])


def test_repair_consistent_rerun_preserves_csv(tmp_path, monkeypatch, capsys):
    import shutil
    processed = tmp_path / "data/processed"
    processed.mkdir(parents=True)
    target = processed / "tc_company_by_industry_monthly.csv"
    shutil.copyfile(recover_gcis_months.PROCESSED, target)
    shutil.copyfile(ROOT / "data/processed/_catalog.json", processed / "_catalog.json")
    original = target.read_bytes()
    monkeypatch.setattr(recover_gcis_months, "ROOT", tmp_path)
    monkeypatch.setattr(recover_gcis_months, "PROCESSED", target)
    recover_gcis_months.main()
    recover_gcis_months.main()
    assert target.read_bytes() == original
    import json
    audit = json.loads((tmp_path / "reports/forecast_real/gcis_recovery_audit.json").read_text(encoding="utf-8"))
    assert audit["recovered_rows"] == 147
    assert audit["remaining_missing_in_recovered_months"] == 0


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
