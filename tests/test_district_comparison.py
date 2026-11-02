"""District comparisons against isolated, deliberately small government-shaped data.

No test reads or initialises the project's populated database.  The ASGI helper
exercises FastAPI's query parsing without an optional httpx dependency.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import api.main as api
import engine.official_labor_market as official
from database.db_manager import DatabaseManager


class DistrictComparisonTests(unittest.TestCase):
    SNAPSHOT = "2026-09-15"
    FETCHED_AT = "2026-09-15T10:00:00+08:00"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(
            prefix="district-comparison-", dir=Path(__file__).resolve().parent
        )
        self.addCleanup(temporary.cleanup)
        self.db = DatabaseManager(Path(temporary.name) / "fixture.db")
        # Build and seed once per case in one transaction; individual DDL
        # commits are disproportionately slow on sandboxed Windows disks.
        self._seed_connection = self.db.get_connection()
        self.addCleanup(self._seed_connection.close)
        schema = Path(__file__).resolve().parents[1] / "database" / "schema.sql"
        self._seed_connection.executescript("BEGIN;\n" + schema.read_text(encoding="utf-8"))
        for target in (official, api):
            patched = patch.object(target, "db", self.db)
            patched.start()
            self.addCleanup(patched.stop)

        # Two postings from the same employer are two advertisements, one company.
        self._job("a1", "大雅區", "機械操作員", 3, "甲公司", "機械操作員")
        self._job("a2", "大雅區", "CNC機台操作", 2, "甲公司", "機械操作員")
        self._job("a3", "大雅區", "生產排程人員", 1, "乙公司", "生產管理人員")
        self._job("a4", "大雅區", "軟體工程師", 4, "丙公司", "軟體工程師")
        self._job("a5", "大雅區", "機械設備軟體工程師", 5, "乙公司", "機械工程師")
        self._job("b1", "潭子區", "機械操作員", 7, "甲公司", "機械操作員")
        self._job("b2", "潭子區", "倉管人員", 2, "", "倉管人員")
        # A large old posting would visibly corrupt the result if snapshots mixed.
        self._job("old", "大雅區", "機械操作員", 99, "舊公司", "機械操作員", "2026-09-01")
        self._audit("大雅區", 5)
        self._audit("潭子區", 2)
        self._audit("神岡區", 0)
        self._seed_connection.commit()
        self._seed_connection.close()
        self._seed_connection = None

    def _write(self, sql, params):
        if self._seed_connection is not None:
            self._seed_connection.execute(sql, params)
        else:
            self.db.execute(sql, params)

    def _job(self, record_id, district, title, openings, company, occupation, snapshot=None):
        self._write(
            """INSERT INTO official_job_vacancies (
                snapshot_date, record_id, district, postal_code, occupation_title,
                occupation_major_code, occupation_major_name, occupation_minor_code,
                occupation_minor_name, openings, work_location, salary_type,
                salary_lower, salary_upper, company_name, updated_date,
                application_deadline, source_url, source_dataset_id, fetched_at
            ) VALUES (?, ?, ?, '428', ?, '07', '工程及操作', ?, ?, ?, ?,
                      '月薪', 32000, 40000, ?, '20260914', '20261231', ?, '44062', ?)""",
            (
                snapshot or self.SNAPSHOT, record_id, district, title,
                occupation, occupation, openings, f"台中市{district}", company,
                f"https://example.invalid/jobs/{record_id}", self.FETCHED_AT,
            ),
        )

    def _audit(self, district, retained, snapshot=None):
        self._write(
            """INSERT INTO official_job_fetch_audit (
                snapshot_date, district, postal_code, returned_count, retained_count,
                excluded_location_count, query_limit, limit_reached, fetched_at
            ) VALUES (?, ?, '428', ?, ?, 0, 1000, 0, ?)""",
            (snapshot or self.SNAPSHOT, district, retained, retained, self.FETCHED_AT),
        )

    def _compare(self, districts=None, **filters):
        return official.get_district_job_comparison(
            districts if districts is not None else ["大雅區", "潭子區"], **filters
        )

    def _get(self, params):
        async def inline_threadpool(function, /, *args, **kwargs):
            return function(*args, **kwargs)

        async def request():
            messages = []
            request_delivered = False

            async def receive():
                nonlocal request_delivered
                if not request_delivered:
                    request_delivered = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                raise AssertionError("GET comparison requested an unexpected body")

            async def send(message):
                messages.append(message)

            path = "/api/official/district-comparison"
            await api.app(
                {
                    "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                    "http_version": "1.1", "method": "GET", "scheme": "http",
                    "path": path, "raw_path": path.encode(), "root_path": "",
                    "query_string": urlencode(params).encode(),
                    "headers": [(b"host", b"testserver")],
                    "server": ("testserver", 80), "client": ("testclient", 1234),
                },
                receive,
                send,
            )
            status = next(message["status"] for message in messages if message["type"] == "http.response.start")
            body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
            return status, json.loads(body)

        # These endpoints and fixtures perform synchronous SQLite work. Running
        # the threadpool inline lets the actual ASGI/router/query parser execute
        # without an event-loop socketpair (blocked in Windows sandboxes).
        with patch("fastapi.routing.run_in_threadpool", inline_threadpool), patch(
            "fastapi.dependencies.utils.run_in_threadpool", inline_threadpool
        ):
            coroutine = request()
            try:
                coroutine.send(None)
            except StopIteration as completed:
                return completed.value
            finally:
                coroutine.close()
        self.fail("Synchronous comparison route unexpectedly required asynchronous IO")

    def test_counts_distinguish_postings_people_and_employers_in_one_snapshot(self):
        result = self._compare(["潭子區", "大雅區"])
        self.assertTrue(result["available"])
        self.assertEqual(result["snapshot_date"], self.SNAPSHOT)
        self.assertEqual([row["district"] for row in result["comparisons"]], ["潭子區", "大雅區"])
        tanzi, daya = result["comparisons"]
        self.assertEqual((daya["vacancy_postings"], daya["requested_workers"], daya["distinct_companies"]), (5, 15, 3))
        self.assertEqual((tanzi["vacancy_postings"], tanzi["requested_workers"], tanzi["distinct_companies"]), (2, 9, 1))
        self.assertEqual(daya["top_occupations"][0], {"name": "機械操作員", "vacancy_postings": 2, "requested_workers": 5})
        for row in result["comparisons"]:
            self.assertEqual(row["coverage_status"], "OBSERVED_SNAPSHOT_COMPLETE_WITHIN_QUERY_LIMIT")
            self.assertEqual(row["query_limit"], 1000)
            self.assertEqual(row["limit_reached_districts"], [])
            self.assertTrue(all(job["snapshot_date"] == self.SNAPSHOT for job in row["top_vacancies"]))
            self.assertEqual(row["evidence"]["data_period"], self.SNAPSHOT)
        self.assertEqual(result["evidence"]["dataset_ids"], ["44062"])

    def test_industry_and_occupation_filters_are_intersection(self):
        result = self._compare(industry_id="IND_MFG", occupation_keyword="  軟體  ")
        self.assertTrue(result["available"])
        self.assertEqual(result["industry_id"], "IND_MFG")
        self.assertTrue(result["industry_name"])
        self.assertEqual(result["occupation_keyword"], "軟體")
        daya, tanzi = result["comparisons"]
        self.assertEqual((daya["vacancy_postings"], daya["requested_workers"]), (1, 5))
        self.assertEqual([job["record_id"] for job in daya["top_vacancies"]], ["a5"])
        self.assertEqual(tanzi["vacancy_postings"], 0)

    def test_valid_empty_district_and_no_matches_are_successful_zeroes(self):
        result = self._compare(["大雅區", "神岡區"], occupation_keyword="不存在的職稱")
        self.assertTrue(result["available"])
        for row in result["comparisons"]:
            self.assertEqual((row["vacancy_postings"], row["requested_workers"], row["distinct_companies"]), (0, 0, 0))
            self.assertEqual(row["top_vacancies"], [])
            self.assertEqual(row["top_occupations"], [])

    def test_three_districts_include_a_fetched_district_without_postings(self):
        status, body = self._get([
            ("districts", "大雅區"), ("districts", "潭子區"), ("districts", "神岡區"),
        ])
        self.assertEqual(status, 200)
        self.assertEqual([row["vacancy_postings"] for row in body["comparisons"]], [5, 2, 0])

    def test_query_cap_is_visible_without_treating_sample_as_complete(self):
        self.db.execute(
            """UPDATE official_job_fetch_audit
               SET returned_count=1000, excluded_location_count=995, limit_reached=1
               WHERE district='大雅區'"""
        )
        result = self._compare()
        self.assertTrue(result["available"])
        daya = result["comparisons"][0]
        self.assertEqual(daya["coverage_status"], "QUERY_LIMIT_REACHED")
        self.assertEqual(daya["limit_reached_districts"], ["大雅區"])
        self.assertEqual(daya["vacancy_postings"], 5)

    def test_missing_audit_cannot_be_reported_as_zero_or_complete(self):
        self.db.execute("DELETE FROM official_job_fetch_audit WHERE district='潭子區'")
        result = self._compare()
        self.assertFalse(result["available"])
        self.assertEqual(result["error_code"], "MISSING_DISTRICT_AUDIT")
        self.assertEqual(result["missing_districts"], ["潭子區"])
        self.assertEqual(result["comparisons"], [])
        status, body = self._get([("districts", "大雅區"), ("districts", "潭子區")])
        self.assertEqual(status, 503)
        self.assertEqual(body["detail"]["error_code"], "MISSING_DISTRICT_AUDIT")

    def test_inconsistent_audit_rejects_comparison_before_filtering(self):
        self.db.execute(
            """UPDATE official_job_fetch_audit SET returned_count=6, retained_count=6
               WHERE district='大雅區'"""
        )
        result = self._compare(occupation_keyword="不存在的職稱")
        self.assertFalse(result["available"])
        self.assertEqual(result["error_code"], "INCOMPLETE_DISTRICT_AUDIT")
        self.assertEqual(result["incomplete_districts"], ["大雅區"])
        self.assertEqual(result["comparisons"], [])

    def test_newer_all_zero_audit_snapshot_does_not_fall_back_to_old_jobs(self):
        self._audit("大雅區", 0, "2026-09-16")
        self._audit("潭子區", 0, "2026-09-16")
        result = self._compare()
        self.assertTrue(result["available"])
        self.assertEqual(result["snapshot_date"], "2026-09-16")
        self.assertEqual([row["vacancy_postings"] for row in result["comparisons"]], [0, 0])

    def test_partial_new_snapshot_never_borrows_an_older_district_audit(self):
        self._audit("大雅區", 0, "2026-09-16")
        result = self._compare()
        self.assertFalse(result["available"])
        self.assertEqual(result["error_code"], "MISSING_DISTRICT_AUDIT")
        self.assertEqual(result["missing_districts"], ["潭子區"])
        self.assertEqual(result["comparisons"], [])

    def test_absent_snapshot_is_unavailable(self):
        self.db.execute("DELETE FROM official_job_vacancies")
        self.db.execute("DELETE FROM official_job_fetch_audit")
        result = self._compare()
        self.assertFalse(result["available"])
        self.assertEqual(result["error_code"], "DATA_UNAVAILABLE")

    def test_api_accepts_repeated_district_queries_and_preserves_filters(self):
        status, body = self._get([
            ("districts", "大雅區"), ("districts", "潭子區"),
            ("industry_id", "IND_MFG"), ("occupation_keyword", "軟體"),
        ])
        self.assertEqual(status, 200)
        self.assertEqual(body["snapshot_date"], self.SNAPSHOT)
        self.assertEqual([row["requested_workers"] for row in body["comparisons"]], [5, 0])

    def test_api_rejects_invalid_duplicate_and_wrong_number_of_districts(self):
        cases = ([], ["大雅區"], ["大雅區", "潭子區", "神岡區", "西屯區"], ["大雅區", "大雅區"], ["大雅區", "臺北市"])
        for districts in cases:
            with self.subTest(districts=districts):
                status, body = self._get([("districts", district) for district in districts])
                self.assertEqual(status, 400)
                self.assertEqual(body["detail"]["error_code"], "INVALID_DISTRICTS")

    def test_api_rejects_unsupported_industry_and_overlong_keyword(self):
        base = [("districts", "大雅區"), ("districts", "潭子區")]
        for extra, code in (
            (("industry_id", "IND_UNKNOWN"), "UNSUPPORTED_INDUSTRY"),
            (("occupation_keyword", "機" * 61), "INVALID_OCCUPATION_KEYWORD"),
        ):
            with self.subTest(code=code):
                status, body = self._get(base + [extra])
                self.assertEqual(status, 400)
                self.assertEqual(body["detail"]["error_code"], code)


if __name__ == "__main__":
    unittest.main()
