"""Isolated GCIS report release tests; no production ETL or database writes."""
import csv
import hashlib
import json
from pathlib import Path

import pytest

from engine.gcis_business_context import capture_gcis_context, _months


SCENARIO = {
    "districts": ["大雅區", "潭子區"],
    "manufacturing": {"division_code": "29", "classification_version": "test-v1"},
    "observation": {"mode": "LATEST_AVAILABLE", "month": None, "window_months": 3, "knowledge_cutoff": None},
}
HEADERS = {
    "setup": ["統一編號", "公司所在地", "資本額", "核准設立日期"],
    "change": ["統一編號", "公司所在地", "資本額", "核准變更日期"],
    "dissolved": ["統一編號", "公司所在地", "資本額", "核准解散日期"],
}


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


@pytest.fixture
def sources(tmp_path):
    processed, raw = tmp_path / "processed", tmp_path / "raw"
    periods = _months("2023-09", "2026-08")
    rows = [[month, "製造業", "new", 10 if month < "2025-09" else 20, ""] for month in periods]
    write_csv(processed / "tc_company_by_industry_monthly.csv",
              ["year_month", "industry", "metric", "companies", "quality_flag"], rows)
    for kind, header in HEADERS.items():
        for month in _months("2026-06", "2026-08"):
            write_csv(raw / "gcis_lists" / kind / f"{month}.csv", header, [])
    return processed, raw


def capture(sources, mapping=None, scenario=None):
    processed, raw = sources
    return capture_gcis_context(scenario or SCENARIO, processed_dir=processed, raw_dir=raw,
                                classification_map=mapping)


def event(sources, kind, month, rows):
    write_csv(sources[1] / "gcis_lists" / kind / f"{month}.csv", HEADERS[kind], rows)


def test_official_24_month_comparison_is_separate_from_local_window(sources):
    result = capture(sources)
    assert result["city"]["start"] == "2025-09"
    assert result["city"]["baseline_start"] == "2024-09"
    assert result["city"]["current_sum"] == 240
    assert result["city"]["baseline_sum"] == 120
    assert result["city"]["change_pct"] == 100
    assert result["local_observation_window"] == {"start": "2026-06", "end": "2026-08"}
    assert any(row["rule_id"] == "GS01_CITY_NEW_UP" for row in result["findings"])
    assert result["city"]["evidence"]["population_scope"] == "OFFICIAL_CITY_AGGREGATE"


def test_fixed_month_never_uses_later_observation_or_claims_historical_knowledge(sources):
    scenario = json.loads(json.dumps(SCENARIO))
    scenario["observation"].update(mode="FIXED_MONTH", month="2026-07")
    event(sources, "setup", "2026-08", [["12345678", "臺中市大雅區一號", 100, "1150801"]])
    result = capture(sources, {"12345678": "29"}, scenario)
    assert result["cutoff_month"] == result["city"]["end"] == "2026-07"
    assert max(row["year_month"] for row in result["city"]["monthly_rows"]) == "2026-07"
    assert result["local"][0]["new_company_count"] is None  # May source is absent, not zero.
    assert result["historical_mode"] == "RETROSPECTIVE_CURRENT_RETAINED_VERSION"
    scenario["observation"]["knowledge_cutoff"] = "2026-07-31"
    with pytest.raises(ValueError, match="HISTORICAL_VINTAGE"):
        capture(sources, scenario=scenario)


def test_missing_city_month_is_not_last_24_rows_or_zero(sources):
    path = sources[0] / "tc_company_by_industry_monthly.csv"
    rows = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))
    write_csv(path, rows[0], [row for row in rows[1:] if row[0] != "2025-10"])
    result = capture(sources)
    assert result["city"]["available"] is False
    assert result["city"]["current_sum"] is None
    assert result["city"]["change_pct"] is None
    assert not any(row["rule_id"] == "GS01_CITY_NEW_UP" for row in result["findings"])


def test_duplicate_official_period_fails_closed(sources):
    path = sources[0] / "tc_company_by_industry_monthly.csv"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("2026-08,製造業,new,20,\n")
    result = capture(sources)
    assert not result["city"]["available"]
    assert "GQ_CITY_DUPLICATE_PERIOD" in result["city"]["evidence"]["reason_codes"]


def test_reprinted_event_deduplicates_and_remains_classified_sample(sources):
    row = ["12345678", "臺中市大雅區一路1號", 100, "1150601"]
    event(sources, "setup", "2026-06", [row])
    event(sources, "setup", "2026-07", [row])
    result = capture(sources, {"12345678": "29"})
    local = result["local"][0]
    assert local["new_company_count"] == 1
    assert local["qualification"] == "PARTIAL"
    assert "GQ_CURRENT_LABEL_RETROSPECTIVE" in local["reason_codes"]
    assert local["evidence"]["comparison_status"] == "DESCRIPTIVE_ONLY"
    assert result["diagnostics"]["duplicate_observations_collapsed"] == 1
    assert any(row["rule_id"] == "GS03_LOCAL_ACTIVITY" and row["district"] == "大雅區" for row in result["findings"])


def test_conflict_cannot_be_silently_sorted_into_a_count(sources):
    event(sources, "setup", "2026-06", [["12345678", "臺中市大雅區一路1號", 100, "1150601"]])
    event(sources, "setup", "2026-07", [["12345678", "臺中市潭子區一路1號", 200, "1150601"]])
    result = capture(sources, {"12345678": "29"})
    assert result["local"][0]["new_company_count"] is None
    assert "GQ_EVENT_CONFLICT" in result["local"][0]["reason_codes"]


def test_no_mapping_is_unknown_and_does_not_guess_business_item_prefix(sources):
    event(sources, "setup", "2026-06", [["12345678", "臺中市大雅區一路1號", 100, "1150601"]])
    cache = sources[1] / "gcis_api_cache"
    cache.mkdir()
    (cache / "company_items.jsonl").write_text('{"id":"12345678","items":["CB01010"]}\n', encoding="utf-8")
    result = capture(sources)
    assert result["local"][0]["new_company_count"] is None
    assert "GQ_CLASSIFICATION_UNAVAILABLE" in result["local"][0]["reason_codes"]
    assert not any(row["rule_id"] == "GS03_LOCAL_ACTIVITY" for row in result["findings"])


def test_sample_zero_requires_complete_files_and_defined_classification(sources):
    event(sources, "setup", "2026-06", [["12345678", "臺中市潭子區一路1號", 100, "1150601"]])
    result = capture(sources, {"12345678": "29"})
    assert result["local"][0]["new_company_count"] == 0
    assert result["local"][0]["evidence"]["per_event_status"]["setup"]["value_status"] == "SAMPLE_MATCH_ZERO"
    (sources[1] / "gcis_lists/setup/2026-07.csv").unlink()
    result = capture(sources, {"12345678": "29"})
    assert result["local"][0]["new_company_count"] is None


def test_three_changes_count_one_company_and_preserve_state_dates(sources):
    event(sources, "setup", "2026-06", [["12345678", "臺中市大雅區一路1號", 100, "1150601"]])
    event(sources, "change", "2026-07", [
        ["12345678", "臺中市大雅區一路1號", 200, "1150701"],
        ["12345678", "臺中市大雅區一路1號", 300, "1150705"],
        ["12345678", "臺中市大雅區一路1號", 400, "1150710"],
    ])
    result = capture(sources, {"12345678": "29"})
    local = result["local"][0]
    assert local["capital_increase_company_count"] == 1
    states = local["evidence"]["capital_state_observations"]
    assert len(states) == 3
    assert states[0]["baseline_date"] == "2026-06-01"
    assert all(state["event_precision"] == "ADJACENT_RETAINED_STATES" for state in states)


def test_first_change_without_baseline_is_unknown(sources):
    event(sources, "change", "2026-07", [["12345678", "臺中市大雅區一路1號", 200, "1150701"]])
    result = capture(sources, {"12345678": "29"})
    assert result["local"][0]["capital_increase_company_count"] is None
    assert result["local"][0]["evidence"]["capital_diagnostics"]["BASELINE_UNKNOWN"] == 1


def test_gapped_capital_state_does_not_become_window_increase(sources):
    event(sources, "setup", "2026-04", [["12345678", "臺中市大雅區一路1號", 100, "1150401"]])
    event(sources, "change", "2026-07", [["12345678", "臺中市大雅區一路1號", 200, "1150701"]])
    result = capture(sources, {"12345678": "29"})
    local = result["local"][0]
    assert local["capital_increase_company_count"] is None
    assert local["evidence"]["capital_state_observations"][0]["event_precision"] == "GAPPED_STATE_COMPARISON"
    assert local["evidence"]["capital_state_observations"][0]["baseline_date"] == "2026-04-01"


def test_mixed_capital_basis_and_missing_values_do_not_count(sources):
    event(sources, "setup", "2026-06", [["12345678", "臺中市大雅區一路1號", 100, "1150601"]])
    write_csv(sources[1] / "gcis_lists/change/2026-07.csv", HEADERS["change"] + ["幣別"],
              [["12345678", "臺中市大雅區一路1號", 200, "1150701", "USD"]])
    assert capture(sources, {"12345678": "29"})["local"][0]["capital_increase_company_count"] is None
    event(sources, "change", "2026-07", [["12345678", "臺中市大雅區一路1號", "", "1150701"]])
    assert capture(sources, {"12345678": "29"})["local"][0]["capital_increase_company_count"] is None


def test_legacy_aggregate_cannot_fill_missing_canonical_count(sources):
    write_csv(sources[0] / "tc_mfg_company_events_monthly.csv",
              ["year_month", "district", "industry_code", "event", "companies"],
              [["2026-08", "大雅區", "29", "new", 123]])
    (sources[1] / "gcis_lists/setup/2026-08.csv").unlink()
    scenario = json.loads(json.dumps(SCENARIO))
    scenario["observation"].update(mode="FIXED_MONTH", month="2026-08")
    result = capture(sources, scenario=scenario)
    assert result["local"][0]["new_company_count"] is None
    assert result["legacy_observations"][0]["legacy_assigned_company_count"] == 123
    assert not result["legacy_observations"][0]["usable_for_official_local_count"]


def test_real_tax_file_can_enable_classification_without_injected_mapping(sources):
    event(sources, "setup", "2026-06", [["12345678", "臺中市大雅區一路1號", 100, "1150601"]])
    write_csv(sources[1] / "tax_registry/bgmopen1_industry.csv", ["統一編號", "行業代號"], [["12345678", "292999"]])
    result = capture(sources)
    assert result["local"][0]["new_company_count"] == 1
    assert any(item["source_id"] == "gcis_tax_classification" for item in result["source_manifest"])


def test_ambiguous_api_item_mapping_is_not_first_code_wins(sources):
    event(sources, "setup", "2026-06", [["12345678", "臺中市大雅區一路1號", 100, "1150601"]])
    cache = sources[1] / "gcis_api_cache"
    cache.mkdir()
    (cache / "company_items.jsonl").write_text('{"id":"12345678","items":["CB01010"]}\n', encoding="utf-8")
    (cache / "item_dgbas.json").write_text('{"CB01010":["2911","2599"]}', encoding="utf-8")
    result = capture(sources)
    assert result["local"][0]["new_company_count"] is None


def test_upstream_hash_and_retained_bytes_are_not_conflated(sources):
    path = sources[1] / "gcis_lists/setup/2026-06.csv"
    retained = hashlib.sha256(path.read_bytes()).hexdigest()
    write_csv(sources[1] / "_manifest.csv", ["path", "url", "sha256", "fetched_at"],
              [["data/raw/gcis_lists/setup/2026-06.csv", "https://data.gcis.nat.gov.tw/od/file?oid=test",
                "a" * 64, "2026-10-05T00:28:53"]])
    result = capture(sources)
    entry = next(row for row in result["source_manifest"] if Path(row["path"]) == path)
    assert entry["sha256"] == entry["retained_sha256"] == retained
    assert entry["upstream_raw_sha256"] == "a" * 64
    assert entry["upstream_hash_status"] == "RECORDED_IN_RETAINED_MANIFEST_NOT_REVALIDATED"
    assert entry["source_url"].endswith("oid=test")


def test_invalid_registry_row_prevents_sample_zero(sources):
    path = sources[1] / "gcis_lists/setup/2026-06.csv"
    path.write_text("統一編號,公司所在地,資本額,核准設立日期\nnot-an-id,臺中市大雅區一路1號,100,1150601\n", encoding="utf-8")
    result = capture(sources)
    assert result["local"][0]["new_company_count"] is None


def test_manifest_hashes_exact_parsed_bytes_once_and_results_are_frozen(sources, monkeypatch):
    path = sources[0] / "tc_company_by_industry_monthly.csv"
    original = path.read_bytes()
    original_read = Path.read_bytes
    reads = []

    def tracked_read(target):
        if target == path:
            reads.append(target)
        return original_read(target)

    monkeypatch.setattr(Path, "read_bytes", tracked_read)
    result = capture(sources)
    entry = next(row for row in result["source_manifest"] if row["source_id"] == "gcis_city_aggregate")
    assert reads == [path]
    assert entry["sha256"] == hashlib.sha256(original).hexdigest()
    path.write_text("invalid", encoding="utf-8")
    assert result["city"]["current_sum"] == 240
    assert capture(sources)["source_release"] != result["source_release"]


def test_gcis_ablation_changes_only_gcis_outputs_and_never_derives_hiring_numbers(sources):
    before = json.loads(json.dumps(SCENARIO))
    before["hiring_plan"] = {"net_hires": 31, "start_month": "2026-11", "end_month": "2027-01"}
    result = capture(sources, scenario=before)
    assert before["hiring_plan"]["net_hires"] == 31
    assert not {"hiring_success_probability", "shortage_workers", "risk_score"} & result.keys()
    path = sources[0] / "tc_company_by_industry_monthly.csv"
    path.unlink()
    absent = capture(sources, scenario=before)
    assert not any(row["rule_id"] == "GS01_CITY_NEW_UP" for row in absent["findings"])
    assert any(row["rule_id"] == "GS07_SOURCE_UNAVAILABLE" for row in absent["findings"])
    assert result["local"] == absent["local"] or result["local"][0]["new_company_count"] == absent["local"][0]["new_company_count"]


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "1.5", ""])
def test_invalid_official_counts_do_not_become_zero_or_truncated_integer(sources, amount):
    path = sources[0] / "tc_company_by_industry_monthly.csv"
    rows = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))
    rows[-1][3] = amount
    write_csv(path, rows[0], rows[1:])
    result = capture(sources)
    assert result["city"]["current_sum"] is None


@pytest.mark.parametrize("mode,month,expected_cutoff", [
    ("LATEST_AVAILABLE", None, "2026-10"),
    ("FIXED_MONTH", "2026-08", "2026-08"),
])
def test_future_only_city_and_lists_are_unknown_not_observed(sources, monkeypatch, mode, month, expected_cutoff):
    monkeypatch.setattr("engine.gcis_business_context._current_month", lambda: "2026-10")
    write_csv(sources[0] / "tc_company_by_industry_monthly.csv",
              ["year_month", "industry", "metric", "companies"],
              [[month, "製造業", "new", 1] for month in _months("2089-01", "2090-12")])
    # Keep no current list files. Future files must not pick the report window,
    # and even a backdated row inside a future list cannot become an observation.
    for kind in HEADERS:
        for path in (sources[1] / "gcis_lists" / kind).glob("*.csv"):
            path.unlink()
        event(sources, kind, "2090-12", [["12345678", "臺中市大雅區一路1號", 100, "1150801"]])
    selected = json.loads(json.dumps(SCENARIO))
    selected["observation"].update(mode=mode, month=month)
    result = capture(sources, {"12345678": "29"}, selected)
    assert result["cutoff_month"] == expected_cutoff
    assert not result["city"]["available"]
    assert result["city"]["current_sum"] is None
    assert all(not row["available"] and row["new_company_count"] is None for row in result["local"])
    assert not any(row["rule_id"] in {"GS01_CITY_NEW_UP", "GS02_CITY_NEW_DOWN", "GS03_LOCAL_ACTIVITY"}
                   for row in result["findings"])
    assert result["diagnostics"]["excluded_future_list_files"] == 3
    assert not any("2090-12.csv" in row["path"] for row in result["source_manifest"])


def test_latest_mixed_city_and_lists_select_latest_nonfuture_period(sources, monkeypatch):
    monkeypatch.setattr("engine.gcis_business_context._current_month", lambda: "2026-10")
    city_path = sources[0] / "tc_company_by_industry_monthly.csv"
    with city_path.open("a", encoding="utf-8") as handle:
        handle.write("2090-12,製造業,new,999999,\n")
    event(sources, "setup", "2026-08", [["12345678", "臺中市大雅區一路1號", 100, "1150801"]])
    for kind in HEADERS:
        event(sources, kind, "2090-12", [["87654321", "臺中市大雅區一路2號", 900, "1150802"]])
    result = capture(sources, {"12345678": "29", "87654321": "29"})
    assert result["cutoff_month"] == result["city"]["end"] == "2026-08"
    assert result["city"]["available"] and result["city"]["current_sum"] == 240
    assert result["local_observation_window"]["end"] == "2026-08"
    assert result["local"][0]["new_company_count"] == 1
    assert "GQ_FUTURE_OBSERVATION_EXCLUDED" in result["city"]["evidence"]["reason_codes"]
    assert not any("2090-12.csv" in row["path"] for row in result["source_manifest"])


def test_fixed_month_keeps_its_cutoff_instead_of_using_latest_month(sources, monkeypatch):
    monkeypatch.setattr("engine.gcis_business_context._current_month", lambda: "2026-10")
    selected = json.loads(json.dumps(SCENARIO))
    selected["observation"].update(mode="FIXED_MONTH", month="2026-07")
    result = capture(sources, scenario=selected)
    assert result["cutoff_month"] == result["city"]["end"] == "2026-07"
    assert result["local_observation_window"]["end"] == "2026-07"
