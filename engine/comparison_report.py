"""Resolve, freeze, build and read official multi-district business reports."""
from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import BASE_DIR, DB_PATH, PROCESSED_DATA_DIR, RAW_DATA_DIR, TAICHUNG_DISTRICTS
from engine.report_scenario import (
    CLASSIFICATION_VERSION, RETRIEVAL_VERSION, DIVISIONS, ReportError,
    digest, index_month, make_hiring_plan, month_index, validate_scenario,
)
from engine.report_sources import capture_database_inputs, capture_factory_inputs, snapshot_dates
from engine.report_store import ReportStore, utc_now


class ComparisonReportService:
    def __init__(self, *, source_db_path=None, store_path=None, processed_dir=None, raw_dir=None, gcis_capture=None):
        self.source_db_path = Path(source_db_path or DB_PATH)
        self.store = ReportStore(store_path or os.environ.get("COMPARISON_REPORT_DB") or (BASE_DIR / "database" / "comparison_reports.sqlite3"))
        self.processed_dir = Path(processed_dir or PROCESSED_DATA_DIR)
        self.raw_dir = Path(raw_dir or RAW_DATA_DIR)
        self.gcis_capture = gcis_capture

    def options(self) -> dict:
        dates = []
        if self.source_db_path.is_file():
            conn = sqlite3.connect(self.source_db_path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                dates = snapshot_dates(conn)
            finally:
                conn.close()
        months = {day[:7] for day in dates}
        city_path = self.processed_dir / "tc_company_by_industry_monthly.csv"
        if city_path.is_file():
            with city_path.open(encoding="utf-8-sig", newline="") as handle:
                months.update(row["year_month"] for row in csv.DictReader(handle) if row.get("year_month"))
        start = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m")
        return {
            "schema_version": "1.0", "districts": TAICHUNG_DISTRICTS,
            "manufacturing_divisions": [{"code": code, "name": name} for code, name in DIVISIONS.items()],
            "classification_version": CLASSIFICATION_VERSION, "retrieval_profile_version": RETRIEVAL_VERSION,
            "job_snapshot_dates": dates, "observation_months": sorted(months, reverse=True), "window_months": [3, 6, 12],
            "defaults": {"districts": ["大雅區", "潭子區", "神岡區"], "division_code": "29", "occupation_keyword": "CNC",
                         "hiring_start_month": start, "hiring_end_month": index_month(month_index(start) + 2)},
        }

    def resolve(self, supplied_scenario: dict) -> dict:
        scenario = validate_scenario(supplied_scenario)
        try:
            jobs, background, sources, _ = capture_database_inputs(self.source_db_path, scenario)
            factories, factory_sources = capture_factory_inputs(self.processed_dir, scenario)
            background["factories"] = factories
            background["forecast"] = {"available": False, "reason": "本版未將全市預測下推至行政區。"}
            if self.gcis_capture:
                gcis = self.gcis_capture(scenario, processed_dir=self.processed_dir, raw_dir=self.raw_dir)
            else:
                from engine.gcis_business_context import capture_gcis_context
                gcis = capture_gcis_context(scenario, processed_dir=self.processed_dir, raw_dir=self.raw_dir)
        except (sqlite3.Error, OSError, UnicodeError, ValueError) as exc:
            raise ReportError("SOURCE_READ_FAILED", "官方資料讀取失敗，未建立報告；請確認本地來源與權限。", 503) from exc
        sources.extend(factory_sources)
        sources.extend(gcis.get("source_manifest", []))
        city = gcis.get("city") or {}
        local = (gcis.get("local") or [{}])[0]
        periods = {
            "jobs": jobs.get("snapshot_date") or jobs.get("requested_snapshot_date"),
            "gcis_local": {"start": local.get("start"), "end": local.get("end")},
            "gcis_city": {key: city.get(key) for key in ("start", "end", "baseline_start", "baseline_end")},
            "wage": (background.get("wage") or {}).get("period"),
            "factory": next((row.get("period") for row in factories if row.get("period")), None),
        }
        manifest = {"schema_version": "1.0", "scenario_hash": digest(scenario), "sources": sources,
                    "resolved_periods": periods, "snapshot_policy": "CAPTURED_VALUES_NO_LATEST_REQUERY", "rules_version": "report-rules-v1"}
        manifest["manifest_hash"] = digest(manifest)
        snapshot = {"scenario": scenario, "manifest": manifest, "jobs": jobs, "gcis": gcis,
                    "background": background, "planning": make_hiring_plan(scenario)}
        token = str(uuid.uuid4())
        expires = time.time() + 15 * 60
        self.store.save_resolution(token, digest(scenario), snapshot, expires)
        return {"resolution_token": token, "scenario": scenario, "resolved_periods": periods,
                "manifest_summary": {"manifest_hash": manifest["manifest_hash"], "source_count": len(sources),
                                     "jobs_available": jobs.get("available", False), "gcis_available": gcis.get("available", False),
                                     "limitations": ["不同資料組各自保留期別。", "回看歷史使用目前留存版本，不代表當時可知資訊。"]},
                "expires_at": datetime.fromtimestamp(expires, ZoneInfo("Asia/Taipei")).isoformat()}

    @staticmethod
    def _data_status(snapshot):
        jobs, gcis = snapshot["jobs"], snapshot["gcis"]
        job_usable = bool(jobs.get("available"))
        gcis_usable = bool((gcis.get("city") or {}).get("available") or any(row.get("available") for row in gcis.get("local", [])))
        background = snapshot.get("background", {})
        others = bool((background.get("wage") or {}).get("available") or any(row.get("available") for row in background.get("factories", [])))
        limited = any(row.get("coverage_status") == "QUERY_LIMIT_REACHED" for row in jobs.get("comparisons", []))
        local_limited = not gcis.get("local") or any(not row.get("available") or row.get("qualification") != "QUALIFIED" for row in gcis.get("local", []))
        if job_usable and gcis_usable and not limited and not local_limited:
            return "USABLE"
        return "LIMITED" if job_usable or gcis_usable or others else "UNAVAILABLE"

    def build(self, payload: dict, idempotency_key: str | None) -> dict:
        if not isinstance(payload, dict) or set(payload) != {"scenario", "resolution_token"}:
            raise ReportError("INVALID_BUILD_REQUEST", "建立報告須包含scenario與resolution_token，不能增加其他欄位。")
        scenario = validate_scenario(payload["scenario"])
        token = payload["resolution_token"]
        if not isinstance(token, str) or not re.fullmatch(r"[a-fA-F0-9-]{36}", token):
            raise ReportError("INVALID_RESOLUTION_TOKEN", "請先解析並確認資料期別。")
        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 128 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", idempotency_key):
            raise ReportError("IDEMPOTENCY_REQUIRED", "請提供8至128字元的Idempotency-Key。")
        request_hash = digest({"scenario": scenario, "resolution_token": token})
        existing = self.store.idempotent_report(idempotency_key, request_hash)
        if existing is not None:
            return existing
        snapshot = self.store.resolution(token, digest(scenario))
        from engine.claim_builder import build_report_content
        report_id = "rep_" + uuid.uuid4().hex
        try:
            content = build_report_content(report_id, scenario, snapshot["manifest"], snapshot["jobs"], snapshot["gcis"], snapshot["planning"], snapshot["background"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ReportError("FACT_CONSISTENCY_FAILED", "官方資料與報告事實契約不一致，已停止建立，請檢查來源版本。", 503) from exc
        report = {"schema_version": "1.0", "report_id": report_id, "request_id": "req_" + uuid.uuid4().hex,
                  "created_at": utc_now(), "build_status": "COMPLETE", "data_status": self._data_status(snapshot),
                  **snapshot, "content": content}
        return self.store.create_report(report, idempotency_key, request_hash)

    def get(self, report_id: str) -> dict:
        return self.store.get_report(report_id)

    def question(self, report_id: str, payload: dict, *, provider=None) -> dict:
        if not isinstance(payload, dict) or set(payload) != {"question"} or not isinstance(payload["question"], str):
            raise ReportError("INVALID_QUESTION", "追問只接受question文字欄位。")
        question = payload["question"].strip()
        if not 1 <= len(question) <= 500:
            raise ReportError("INVALID_QUESTION", "問題請輸入1至500字。")
        report = self.get(report_id)
        from agent.report_assistant import answer_report_question
        try:
            answer = answer_report_question({**report["content"], "scenario": report["scenario"]}, question, provider=provider)
        except (ValueError, KeyError, TypeError) as exc:
            if str(exc) == "RENDER_CONTRACT_INCOMPATIBLE":
                raise ReportError("RENDER_CONTRACT_INCOMPATIBLE", "報告顯示規則已更新，請建立新版報告後追問；原報告仍可閱讀與匯出。", 409) from exc
            raise ReportError("FACT_CONSISTENCY_FAILED", "報告主張核驗未通過，不顯示未驗證內容。", 503) from exc
        self.store.save_answer_event(report_id, answer, hashlib.sha256(question.encode("utf-8")).hexdigest(), len(question))
        return answer

    def export_html(self, report_id: str) -> str:
        report = self.get(report_id)
        esc = lambda text: html.escape(str(text if text is not None else "未知"), quote=True)
        blocks = report.get("content", {}).get("summary_blocks", [])
        paragraphs = "".join(f"<p>{esc(block.get('text', ''))}</p>" for block in blocks)
        facts = {fact["fact_id"]: fact for fact in report.get("content", {}).get("facts", [])}
        units = {"person": "人", "posting": "筆", "company": "家公司", "company_name": "個不同公司名稱", "factory": "家工廠", "TWD": "元"}
        table_rows = []
        for group in report.get("content", {}).get("metric_groups", []):
            group_rows = group.get("rows", [])
            if not any(row.get("district") for row in group_rows):
                continue
            cells, periods = [], set()
            for district in report["scenario"]["districts"]:
                row = next((item for item in group_rows if item.get("district") == district), {})
                fact = facts.get(row.get("fact_id"), {})
                period = fact.get("period", {})
                if period:
                    periods.add(period["start"] if period["start"] == period["end"] else period["start"] + "～" + period["end"])
                status, value = row.get("value_status"), row.get("value")
                if status == "UNKNOWN" or value is None:
                    label = "未知；資料不足"
                elif status == "SAMPLE_MATCH_ZERO":
                    label = "已分類樣本未觀察到"
                else:
                    label = ("至少 " if status == "LOWER_BOUND" else "") + str(value) + " " + units.get(group.get("unit"), str(group.get("unit")))
                cells.append("<td>" + esc(label) + "</td>")
            eligibility = "同條件公開樣本可比較" if group.get("comparison_status") == "COMPARABLE_SAMPLE" else "僅描述；不作區域排名"
            table_rows.append("<tr><th scope='row'>" + esc(group.get("label")) + "<br><small>" + esc("、".join(sorted(periods)) or "無可用期別") + "；" + esc(eligibility) + "</small></th>" + "".join(cells) + "</tr>")
        rows = "".join(table_rows)
        headings = "".join(f"<th>{esc(district)}</th>" for district in report["scenario"]["districts"])
        plan = "".join(f"<li>{esc(row['month'])}：{esc(row['people'])} 人</li>" for row in report["planning"]["monthly_targets"])
        evidence = "".join(f"<li><pre>{esc(json.dumps(item, ensure_ascii=False, indent=2))}</pre></li>" for item in report.get("content", {}).get("evidence", []))
        return ("<!doctype html><html lang='zh-Hant'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>企業招募環境比較報告</title><style>body{font:16px/1.7 system-ui;color:#17302d;max-width:1050px;margin:30px auto;padding:0 20px}"
                "table{border-collapse:collapse;width:100%}th,td{border:1px solid #b5c7bf;padding:10px;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
                "@media print{body{margin:0}h2{break-after:avoid}tr,li,p{break-inside:avoid}}</style><body><h1>企業招募環境比較報告</h1>"
                f"<p>報告 {esc(report_id)}｜資料狀態 {esc(report['data_status'])}｜建立 {esc(report['created_at'])}</p>"
                f"<p>職類：{esc(report['scenario']['occupation']['keyword'])}；製造中類：{esc(report['scenario']['manufacturing']['division_code'])}</p>"
                f"<h2>核准摘要與限制</h2>{paragraphs}<h2>各來源的固定觀察</h2><table><thead><tr><th>指標與期別</th>{headings}</tr></thead><tbody>{rows}</tbody></table>"
                f"<h2>企業招募計畫</h2><p>{esc(report['planning']['disclosure'])}</p><ul>{plan}</ul><h2>來源期別與版本</h2>"
                f"<pre>{esc(json.dumps(report['manifest'], ensure_ascii=False, indent=2))}</pre><h2>證據</h2><ul>{evidence}</ul></body></html>")
