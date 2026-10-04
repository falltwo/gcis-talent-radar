import unittest
from pathlib import Path

from fastapi import HTTPException

from api.main import get_overview, official_company_trend, official_wage_baseline
from agent.tool_router import execute_tool
from database.db_manager import db
from engine.evidence_engine import build_evidence_object
from engine.official_labor_market import (
    get_gcis_new_company_trend,
    get_regional_job_demand,
    get_wage_baseline,
)


class OfficialDataToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_gcis_manufacturing_uses_real_monthly_series(self):
        result = get_gcis_new_company_trend("IND_MFG", months=6)
        self.assertTrue(result["available"])
        self.assertEqual(result["official_industry"], "製造業")
        self.assertEqual(result["latest_month"], "2026-08")
        self.assertEqual(result["latest_new_companies"], 75)
        self.assertEqual(result["missing_months"], ["2025-08", "2025-09"])
        self.assertIsNone(result["complete_window_change_pct"])
        self.assertEqual(result["evidence"]["dataset_ids"], ["01E5CFC6-9F09-4CB5-BE81-22B451E4B1BD"])

    def test_taiwanjobs_daya_is_location_filtered(self):
        result = get_regional_job_demand("大雅區", "IND_MFG")
        self.assertTrue(result["available"])
        self.assertGreater(result["vacancy_postings"], 0)
        self.assertGreater(result["requested_workers"], 0)
        self.assertEqual(result["evidence"]["dataset_ids"], ["44062"])
        for vacancy in result["top_vacancies"]:
            self.assertIn("台中市大雅區", vacancy["work_location"].replace("臺", "台"))

    def test_all_taichung_districts_were_fetched(self):
        latest = db.fetch_one("SELECT MAX(snapshot_date) AS snapshot_date FROM official_job_fetch_audit")
        self.assertIsNotNone(latest["snapshot_date"])
        count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM official_job_fetch_audit WHERE snapshot_date = ?",
            (latest["snapshot_date"],),
        )["count"]
        self.assertEqual(count, 29)

    def test_labor_insurance_manufacturing_baseline(self):
        result = get_wage_baseline("IND_MFG")
        self.assertTrue(result["available"])
        self.assertEqual(result["data_period"], "11412")
        self.assertEqual(result["insured_units"], 20056)
        self.assertEqual(result["insured_people"], 361509)
        self.assertAlmostEqual(result["average_insured_salary"], 36201.78, places=2)
        self.assertEqual(result["evidence"]["dataset_ids"], ["100999"])

    def test_unknown_industry_is_rejected_without_manufacturing_fallback(self):
        invalid_id = "NOT_A_REAL_INDUSTRY"
        cases = (
            get_regional_job_demand(industry_id=invalid_id),
            get_gcis_new_company_trend(invalid_id),
            get_wage_baseline(invalid_id),
            execute_tool("COMPANY_TREND_QUERY", {"industry_id": invalid_id})["data"],
            execute_tool("WAGE_QUERY", {"industry_id": invalid_id})["data"],
        )
        for result in cases:
            self.assertFalse(result["available"])
            self.assertEqual(result["error_code"], "UNSUPPORTED_INDUSTRY")
            self.assertEqual(result["requested_industry_id"], invalid_id)
            self.assertNotIn("latest_new_companies", result)
            self.assertNotIn("insured_people", result)

        for endpoint, args in (
            (official_company_trend, (invalid_id, 36)),
            (official_wage_baseline, (invalid_id,)),
        ):
            with self.assertRaises(HTTPException) as context:
                endpoint(*args)
            self.assertEqual(context.exception.status_code, 400)
            self.assertEqual(context.exception.detail["error_code"], "UNSUPPORTED_INDUSTRY")

    def test_official_tables_do_not_contain_legacy_104_source(self):
        schema = " ".join(
            row["sql"] or ""
            for row in db.fetch_all(
                "SELECT sql FROM sqlite_master WHERE name IN "
                "('official_job_vacancies','gcis_new_company_monthly','labor_insurance_baseline')"
            )
        )
        self.assertNotIn("104_GCIS_LINKED", schema)

    def test_evidence_uses_recorded_timestamp_without_today_fallback(self):
        evidence = build_evidence_object(
            intent="TEST",
            indicator_name="timestamp contract",
            calculation_steps=[],
            source_tables=["test_table"],
            official_sources=["test source"],
        )
        self.assertIsNone(evidence["last_updated"])
        self.assertEqual(evidence["timestamp_status"], "NOT_RECORDED")

        recorded = "2026-10-05T00:00:00+08:00"
        evidence = build_evidence_object(
            intent="TEST",
            indicator_name="timestamp contract",
            calculation_steps=[],
            source_tables=["test_table"],
            official_sources=["test source"],
            fetched_at=recorded,
        )
        self.assertEqual(evidence["last_updated"], recorded)
        self.assertEqual(evidence["timestamp_status"], "SOURCE_TIMESTAMP")

    def test_official_tools_report_database_refresh_timestamps(self):
        job = get_regional_job_demand("大雅區", "IND_MFG")
        expected_job = db.fetch_one(
            "SELECT MAX(fetched_at) AS refreshed_at FROM official_job_fetch_audit"
        )["refreshed_at"]
        self.assertEqual(job["evidence"]["last_updated"], expected_job)

        company = get_gcis_new_company_trend("IND_MFG", months=6)
        expected_company = db.fetch_one(
            "SELECT MAX(loaded_at) AS refreshed_at FROM gcis_new_company_monthly"
        )["refreshed_at"]
        self.assertEqual(company["evidence"]["last_updated"], expected_company)

        wage = get_wage_baseline("IND_MFG")
        expected_wage = db.fetch_one(
            "SELECT MAX(loaded_at) AS refreshed_at FROM labor_insurance_baseline"
        )["refreshed_at"]
        self.assertEqual(wage["evidence"]["last_updated"], expected_wage)

    def test_overview_separates_official_refresh_from_mart_build_times(self):
        overview = get_overview()
        official_times = overview["dataset_refresh_times"]
        expected_official = max(value for value in official_times.values() if value)

        self.assertEqual(overview["last_updated"], expected_official)
        self.assertEqual(overview["last_updated_type"], "OFFICIAL_SOURCE_FETCH_OR_LOAD")
        self.assertIn("official source", overview["last_updated_scope"])
        self.assertEqual(
            set(official_times),
            {
                "official_job_vacancies",
                "gcis_new_company_monthly",
                "labor_insurance_baseline",
            },
        )
        self.assertIn("mismatch_signal_mart", overview["derived_mart_build_times"])
        self.assertNotEqual(
            overview["last_updated"],
            overview["derived_mart_build_times"]["mismatch_signal_mart"],
        )

    def test_unverifiable_legacy_timestamps_are_cleared(self):
        forbidden = "2026" + "-10-01"
        for table in ("companies", "industry_dynamics_mart", "department_indicators_mart"):
            count = db.fetch_one(
                f"SELECT COUNT(*) AS count FROM {table} WHERE updated_at = ?",
                (forbidden,),
            )["count"]
            self.assertEqual(count, 0, table)

        root = Path(__file__).resolve().parent.parent
        for relative_path in (
            "data/processed/companies_taichung_cleaned.csv",
            "data/marts/industry_dynamics_mart.csv",
            "data/marts/department_indicators_mart.csv",
        ):
            self.assertNotIn(
                forbidden,
                (root / relative_path).read_text(encoding="utf-8-sig"),
                relative_path,
            )

    def test_executable_code_has_no_hard_coded_refresh_date(self):
        root = Path(__file__).resolve().parent.parent
        forbidden = "2026" + "-10-01"
        source_roots = (
            root / "api",
            root / "agent",
            root / "engine",
            root / "etl",
            root / "tests",
        )
        offenders = [
            str(path.relative_to(root))
            for source_root in source_roots
            for path in source_root.rglob("*.py")
            if forbidden in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
