"""Independent review regressions for immutable report source validation."""
import sqlite3

import pytest

from tests.test_comparison_report import service, scenario, build


@pytest.mark.parametrize("bad_openings", [-1, 1.5])
def test_invalid_source_worker_count_never_becomes_verified_aggregate(service, bad_openings):
    # SQLite INTEGER affinity does not prohibit negative or fractional values.
    conn = sqlite3.connect(service.source_db_path)
    conn.execute("UPDATE official_job_vacancies SET openings=? WHERE record_id='a1'", (bad_openings,))
    conn.commit()
    conn.close()
    report = build(service)
    assert not report["jobs"].get("available"), "Bad source counts must make the job snapshot unusable, not be truncated/summed."
    assert not any(f["metric_id"].startswith("jobs.") for f in report["content"]["facts"])


def test_malformed_source_snapshot_cannot_be_marked_usable(service):
    conn = sqlite3.connect(service.source_db_path)
    for table in ("official_job_vacancies", "official_job_fetch_audit"):
        conn.execute(f"UPDATE {table} SET snapshot_date='2026-99-99'")
    conn.commit()
    conn.close()
    report = build(service)
    assert not report["jobs"].get("available"), "The source-level availability must agree with real calendar validation."


def test_latest_future_only_wage_is_unavailable_not_observed(service):
    with sqlite3.connect(service.source_db_path) as conn:
        conn.execute("UPDATE labor_insurance_baseline SET data_period='17912'")
    report = build(service)
    assert not report["background"]["wage"]["available"]
    assert not any(f["metric_id"] == "wage.average_insured_salary" for f in report["content"]["facts"])


def test_latest_wage_ignores_future_row_and_keeps_latest_valid_history(service):
    with sqlite3.connect(service.source_db_path) as conn:
        conn.execute("""INSERT INTO labor_insurance_baseline
            SELECT '17912',region_code,region_name,unit_type_code,unit_type_name,
                   industry_code,industry_name,employment_insurance_code,employment_insurance_name,
                   insured_units,insured_people,99999,source_dataset_id,source_url,loaded_at
            FROM labor_insurance_baseline WHERE data_period='11412'""")
    report = build(service)
    wage = report["background"]["wage"]
    assert wage["available"] and wage["period"] == "2025-12"
    assert wage["average_insured_salary"] == 36201.78
    facts = [fact for fact in report["content"]["facts"] if fact["metric_id"] == "wage.average_insured_salary"]
    assert len(facts) == 1 and facts[0]["period"]["start"] == "2025-12"


def test_fixed_wage_cutoff_stays_historical(service):
    selected = scenario()
    selected["observation"].update(mode="FIXED_MONTH", month="2025-11")
    report = build(service, selected)
    assert not report["background"]["wage"]["available"]
    assert not any(f["metric_id"] == "wage.average_insured_salary" for f in report["content"]["facts"])
