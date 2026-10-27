"""Capture approved report inputs without mutating the source database."""
from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from engine.official_labor_market import _read_district_comparison_snapshot, get_district_job_comparison
from engine.report_scenario import DIVISIONS, digest, month_index, ReportError


def _has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def snapshot_dates(conn) -> list[str]:
    dates = set()
    for table in ("official_job_vacancies", "official_job_fetch_audit"):
        if _has_table(conn, table):
            dates.update(row[0] for row in conn.execute(f"SELECT DISTINCT snapshot_date FROM {table}") if row[0])
    return sorted(dates)


def _wage(conn, cutoff_month):
    # Latest observed data must not select an accidentally future-dated row.
    # A requested historical month retains its own, stricter observation cutoff.
    cutoff_month = cutoff_month or datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m")
    if not _has_table(conn, "labor_insurance_baseline"):
        return {"available": False, "reason": "尚未匯入平均投保薪資。"}
    rows = [dict(row) for row in conn.execute(
        "SELECT * FROM labor_insurance_baseline WHERE region_code='66' AND unit_type_code='1' "
        "AND employment_insurance_code='1' AND industry_code='C' ORDER BY data_period DESC"
    )]
    eligible = []
    for row in rows:
        period = str(row["data_period"])
        if len(period) != 5 or not period.isdigit() or not 1 <= int(period[3:]) <= 12:
            continue
        month = f"{int(period[:3]) + 1911:04d}-{period[3:]}"
        if month <= cutoff_month:
            eligible.append((row, month))
    if not eligible:
        return {"available": False, "reason": "指定觀測期沒有可用的年末平均投保薪資。"}
    row, month = eligible[0]
    try:
        amount = Decimal(str(row["average_insured_salary"]))
        people = Decimal(str(row["insured_people"]))
        if not amount.is_finite() or amount < 0 or not people.is_finite() or people <= 0 or people != people.to_integral_value():
            raise ValueError("unusable salary")
    except (InvalidOperation, TypeError, ValueError):
        return {"available": False, "reason": "此期投保薪資或投保人數不可計算，不能將缺值當零。"}
    evidence = {
        "evidence_id": f"ev_wage_{row['data_period']}", "dataset_id": "100999",
        "source_urls": ["https://data.gov.tw/dataset/100999"],
        "source": ["勞動部勞工保險局－投保單位、人數及平均投保薪資"],
        "data_period": month, "geography": "臺中市", "last_updated": row.get("loaded_at"),
        "row_locator": {"table": "labor_insurance_baseline", "data_period": row["data_period"], "region_code": "66", "industry_code": "C", "unit_type_code": "1", "employment_insurance_code": "1"},
        "limitations": ["平均投保薪資不是實領、職缺開薪或中位薪資。", "限定製造業C、產業勞工及交通公用事業員工類別1、參加就保註記1；不是所有受僱者或全行業平均。", "使用目前留存版本回看觀測期，不重建當時可知資訊。"],
    }
    return {"available": True, "average_insured_salary": float(amount), "data_period": row["data_period"],
            "period": month, "region": "臺中市", "industry_code": "C", "unit_type_code": "1", "employment_insurance_code": "1",
            "metric_label": "全市製造業產業勞工（參加就保口徑）平均投保薪資", "evidence": evidence,
            "source_row_hash": digest(row)}


def capture_database_inputs(source_db_path, scenario):
    path = Path(source_db_path)
    jobs = {"available": False, "error_code": "DATA_UNAVAILABLE", "reason": "尚未匯入官方職缺快照。", "comparisons": []}
    background = {"wage": {"available": False, "reason": "來源資料庫尚未匯入。"}}
    sources, dates = [], []
    selected_date = None
    if not path.is_file():
        return jobs, background, sources, dates
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        dates = snapshot_dates(conn)
        observation = scenario["observation"]
        if observation["mode"] == "FIXED_MONTH":
            matching = [day for day in dates if day[:7] == observation["month"]]
            selected_date = matching[-1] if matching else None
        else:
            selected_date = dates[-1] if dates else None
        if selected_date and all(_has_table(conn, name) for name in ("official_job_vacancies", "official_job_fetch_audit")):
            jobs = get_district_job_comparison(
                scenario["districts"], "IND_MFG", scenario["occupation"]["keyword"],
                snapshot_date=selected_date, connection=conn,
            )
            _, rows, audits = _read_district_comparison_snapshot(scenario["districts"], selected_date, conn)
            try:
                source_hash = digest({"records": rows, "audits": audits})
            except ValueError:
                source_hash = hashlib.sha256(repr((rows, audits)).encode("utf-8")).hexdigest()
                jobs = {"available": False, "error_code": "INVALID_SOURCE_NUMERIC_VALUE", "reason": "來源含非有限數值，暫停本次職缺比較。", "comparisons": []}
            if jobs.get("available") and selected_date > datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat():
                jobs = {"available": False, "error_code": "FUTURE_SOURCE_SNAPSHOT", "reason": "來源觀測日位於未來，不能當作已觀察職缺。", "comparisons": []}
            for comparison in jobs.get("comparisons", []):
                sample = comparison.pop("top_vacancies", [])
                comparison["source_vacancy_refs"] = [{"record_id": item["record_id"], "source_url": item.get("source_url")} for item in sample]
                comparison.setdefault("evidence", {})["row_locator"] = {
                    "table": "official_job_vacancies", "snapshot_date": selected_date, "district": comparison["district"],
                    "occupation_keyword": scenario["occupation"]["keyword"], "retrieval_profile": "IND_MFG",
                    "retrieval_profile_version": "job-rules-v1", "source_snapshot_hash": source_hash,
                    "sample_record_ids": [item["record_id"] for item in sample],
                }
            sources.append({"dataset_id": "44062", "snapshot_id": selected_date,
                            "artifact_hash": source_hash, "row_count": len(rows),
                            "audit_count": len(audits), "source_type": "OFFICIAL_DATABASE_SNAPSHOT",
                            "source_url": "https://data.gov.tw/dataset/44062", "retrieval_rules_version": "job-rules-v1"})
        elif observation["mode"] == "FIXED_MONTH":
            jobs = {"available": False, "error_code": "HISTORICAL_SNAPSHOT_NOT_AVAILABLE", "reason": "指定月份未留存職缺快照，不使用較晚資料補位。", "comparisons": []}
        cutoff = observation["month"] if observation["mode"] == "FIXED_MONTH" else None
        background["wage"] = _wage(conn, cutoff)
        if background["wage"].get("available"):
            sources.append({"dataset_id": "100999", "snapshot_id": background["wage"]["data_period"],
                            "artifact_hash": background["wage"]["source_row_hash"], "source_type": "OFFICIAL_DATABASE_SNAPSHOT"})
    finally:
        conn.close()
    try:
        valid_selected_date = selected_date if selected_date and date.fromisoformat(selected_date).isoformat() == selected_date and selected_date <= datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat() else None
    except (TypeError, ValueError):
        valid_selected_date = None
    jobs["requested_snapshot_date"] = valid_selected_date
    return jobs, background, sources, dates


def capture_factory_inputs(processed_dir, scenario):
    path = Path(processed_dir) / "tc_factory_count_district_monthly.csv"
    absent = [{"district": district, "available": False, "reason": "尚無可精確對應的區域中類工廠快照。"} for district in scenario["districts"]]
    if not path.is_file():
        return absent, []
    data = path.read_bytes()
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    if not rows or not {"year_month", "district", "industry", "factories"} <= set(rows[0]):
        return absent, []
    cutoff = scenario["observation"]["month"] or datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m")
    valid_periods = set()
    for row in rows:
        try:
            month_index(row["year_month"])
            if row["year_month"] <= cutoff:
                valid_periods.add(row["year_month"])
        except ReportError:
            continue
    periods = sorted(valid_periods)
    if not periods:
        return absent, []
    period = periods[-1]
    industry = DIVISIONS[scenario["manufacturing"]["division_code"]]
    result = []
    for missing in absent:
        selected = [row for row in rows if row["year_month"] == period and row["district"] == missing["district"] and row["industry"] == industry]
        try:
            if len(selected) != 1:
                raise ValueError("not an exact category match")
            count = Decimal(selected[0]["factories"])
            if not count.is_finite() or count < 0 or count != count.to_integral_value():
                raise ValueError("not a valid count")
        except (ValueError, InvalidOperation, TypeError):
            result.append({**missing, "period": period, "industry_name": industry})
            continue
        result.append({"district": missing["district"], "available": True, "factory_count": int(count), "period": period, "industry_name": industry,
                       "evidence": {"evidence_id": "ev_factory_" + digest(selected)[:16], "source": ["臺中市政府經濟發展局工廠產業類別與行政區家數"],
                                    "source_urls": ["https://data.gov.tw/dataset/174209"], "dataset_id": "174209", "data_period": period,
                                    "geography": missing["district"], "row_locator": selected[0],
                                    "limitations": ["工廠家數不是公司總家數或徵才家數。", "僅在名稱精確對應時提供中類數值。"]}})
    return result, [{"dataset_id": "174209", "snapshot_id": period, "artifact_hash": hashlib.sha256(data).hexdigest(),
                     "source_type": "OFFICIAL_PROCESSED_FILE", "file": path.name}]
