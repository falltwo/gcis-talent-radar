import unittest

from database.db_manager import db
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

    def test_official_tables_do_not_contain_legacy_104_source(self):
        schema = " ".join(
            row["sql"] or ""
            for row in db.fetch_all(
                "SELECT sql FROM sqlite_master WHERE name IN "
                "('official_job_vacancies','gcis_new_company_monthly','labor_insurance_baseline')"
            )
        )
        self.assertNotIn("104_GCIS_LINKED", schema)


if __name__ == "__main__":
    unittest.main()
