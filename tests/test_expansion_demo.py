"""展示主線：路由合約與真實官方快照測試；ASGI 呼叫不依賴額外 HTTP 客戶端。"""
import asyncio
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit
from unittest.mock import patch

import pytest

from api.main import app
from engine.expansion_demo import build_expansion_report, load_factory_snapshot
from engine.official_labor_market import get_regional_job_demand


def _get(url, *, params=None):
    """以 ASGI 介面真正送 GET 到應用程式，涵蓋 FastAPI 參數驗證。"""
    parsed = urlsplit(url)
    query = urlencode(params if params is not None else parse_qsl(parsed.query))
    messages = []

    async def exchange():
        received = False

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.sleep(0)
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        await app({
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": parsed.path,
            "raw_path": parsed.path.encode(), "root_path": "", "query_string": query.encode(),
            "headers": [], "client": ("test", 12345), "server": ("test", 80),
        }, receive, send)

    asyncio.run(exchange())
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    headers = {key.decode(): value.decode() for key, value in start["headers"]}
    return SimpleNamespace(
        status_code=start["status"], headers=headers, text=body.decode("utf-8"),
        json=lambda: json.loads(body),
    )


def _fixture(path: Path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["year_month", "district", "industry", "factories"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_factory_latest_complete_month_no_missing_as_zero(tmp_path):
    path = _fixture(tmp_path / "factories.csv", [
        {"year_month": "2025-07", "district": "大雅區", "industry": "機械設備製造業", "factories": 8},
        {"year_month": "2025-09", "district": "大雅區", "industry": "機械設備製造業", "factories": 10},
        {"year_month": "2025-09", "district": "大雅區", "industry": "金屬製品製造業", "factories": 20},
        {"year_month": "2025-09", "district": "西屯區", "industry": "機械設備製造業", "factories": 30},
    ])
    item = load_factory_snapshot("大雅區", path)
    assert item["available"] is True
    assert item["period"] == "2025-09"
    assert item["factory_count"] == 30
    assert item["top_industries"][0] == {"industry": "金屬製品製造業", "factories": 20}
    assert item["source_url"] == "https://data.gov.tw/dataset/174209"
    assert "職缺" in " ".join(item["limitations"])


def test_factory_latest_month_absent_in_district_is_unavailable(tmp_path):
    path = _fixture(tmp_path / "factories.csv", [
        {"year_month": "2025-07", "district": "大雅區", "industry": "機械設備製造業", "factories": 8},
        {"year_month": "2025-09", "district": "西屯區", "industry": "機械設備製造業", "factories": 30},
    ])
    item = load_factory_snapshot("大雅區", path)
    assert item["available"] is False
    assert item["period"] == "2025-09"
    assert "factory_count" not in item


@pytest.mark.parametrize("rows", [
    [{"year_month": "2025-09", "district": "大雅區", "industry": "機械設備製造業", "factories": -1}],
    [{"year_month": "2025-09", "district": "大雅區", "industry": "機械設備製造業", "factories": "not a number"}],
    [
        {"year_month": "2025-09", "district": "大雅區", "industry": "機械設備製造業", "factories": 3},
        {"year_month": "2025-09", "district": "大雅區", "industry": "機械設備製造業", "factories": 3},
    ],
])
def test_factory_invalid_or_duplicate_rows_fail_closed(tmp_path, rows):
    item = load_factory_snapshot("大雅區", _fixture(tmp_path / "factories.csv", rows))
    assert item["available"] is False
    assert "factory_count" not in item


def test_factory_missing_file_does_not_invent_data(tmp_path):
    assert load_factory_snapshot("大雅區", tmp_path / "missing.csv")["available"] is False


def test_report_partial_does_not_turn_missing_jobs_into_zero(tmp_path):
    path = _fixture(tmp_path / "factories.csv", [
        {"year_month": "2025-09", "district": "大雅區", "industry": "機械設備製造業", "factories": 8},
    ])
    with patch("engine.expansion_demo.get_regional_job_demand", return_value={"available": False, "reason": "無快照"}), \
         patch("engine.expansion_demo.get_gcis_new_company_trend", return_value={"available": False, "reason": "無月報"}), \
         patch("engine.expansion_demo.get_wage_baseline", return_value={"available": False, "reason": "無年報"}):
        report = build_expansion_report("大雅區", 10, factory_path=path)
    assert report["status"] == "partial"
    assert report["job_demand"] == {"available": False, "reason": "無快照"}
    assert report["scenario"]["planned_hires"] == 10
    assert "需補職務、薪資與招募時程" in report["interpretation"]
    assert "risk_score" not in report
    assert "職缺" in " ".join(report["factory_snapshot"]["limitations"])


def test_wage_without_observed_average_is_unavailable_not_zero(tmp_path):
    path = _fixture(tmp_path / "factories.csv", [
        {"year_month": "2025-09", "district": "大雅區", "industry": "機械設備製造業", "factories": 8},
    ])
    with patch("engine.expansion_demo.get_regional_job_demand", return_value={"available": False}), \
         patch("engine.expansion_demo.get_gcis_new_company_trend", return_value={"available": False}), \
         patch("engine.expansion_demo.get_wage_baseline", return_value={"available": True, "average_insured_salary": None}):
        report = build_expansion_report("大雅區", 10, factory_path=path)
    assert report["wage_baseline"]["available"] is False
    assert "average_insured_salary" not in report["wage_baseline"]


def test_api_real_snapshot_and_scenario_are_separate():
    response = _get("/api/demo/expansion?district=大雅區&planned_hires=10")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["scenario"] == {"district": "大雅區", "planned_hires": 10, "industry": "製造業"}
    assert data["factory_snapshot"]["period"] == "2026-07"
    assert data["factory_snapshot"]["factory_count"] == 989
    assert data["company_trend"]["latest_month"] == "2026-08"
    assert data["company_trend"]["latest_new_companies"] == 75
    assert data["company_trend"]["evidence"]["geography"] == "臺中市（全市）"
    assert data["job_demand"]["district"] == "大雅區"
    assert data["job_demand"]["snapshot_date"]
    assert data["job_demand"]["evidence"]["dataset_ids"] == ["44062"]
    assert data["wage_baseline"]["metric_label"] == "平均投保薪資（非實領薪資）"
    assert "預計招募 10 人" in data["interpretation"]
    assert f"{data['job_demand']['vacancy_postings']} 筆" in data["interpretation"]
    assert "需補職務、薪資與招募時程" in data["interpretation"]
    assert "risk_score" not in data


@pytest.mark.parametrize("params", [
    {"district": "台北市", "planned_hires": 10},
    {"district": "大雅區", "planned_hires": 0},
    {"district": "大雅區", "planned_hires": -1},
    {"district": "大雅區", "planned_hires": 100001},
    {"district": "大雅區", "planned_hires": "abc"},
])
def test_api_rejects_invalid_scope_and_target(params):
    assert _get("/api/demo/expansion", params=params).status_code == 422


def test_zero_observed_postings_is_not_missing():
    result = get_regional_job_demand("和平區", "IND_MFG")
    assert result["available"] is True
    assert result["vacancy_postings"] == 0
    assert result["requested_workers"] == 0


def test_missing_district_fetch_audit_is_not_misreported_as_zero():
    with patch("engine.official_labor_market.db.fetch_one", return_value={"snapshot_date": "2026-10-05"}), \
         patch("engine.official_labor_market.db.fetch_all", side_effect=[[], []]):
        result = get_regional_job_demand("大雅區", "IND_MFG")
    assert result["available"] is False
    assert "vacancy_postings" not in result
    assert "requested_workers" not in result


def test_demo_page_is_served_and_root_points_to_it():
    page = _get("/demo")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "大雅區" in page.text


def test_root_is_new_home_with_question_box_and_expansion_scenario():
    page = _get("/")
    assert page.status_code == 200
    # 首頁要能直接問問題，並走真實的 agent API
    assert 'id="ask-form"' in page.text
    assert "/api/agent/chat" in page.text
    # 建議問題按鈕
    assert 'class="suggest"' in page.text
    # 擴廠情境仍在首頁
    assert "/api/demo/expansion" in page.text
    # 舊原型的模擬指標不能出現在新首頁
    assert "65 題" not in page.text


def test_legacy_prototype_moves_to_legacy_route():
    page = _get("/legacy")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "舊版原型" in page.text
