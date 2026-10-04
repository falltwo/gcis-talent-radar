"""初賽展示主線：真實官方資料、使用者情境及限制分離，不產生預測分數。"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from config import PROCESSED_DATA_DIR
from engine.official_labor_market import (
    get_gcis_new_company_trend,
    get_regional_job_demand,
    get_wage_baseline,
)

FACTORY_SOURCE_URL = "https://data.gov.tw/dataset/174209"
FACTORY_PATH = PROCESSED_DATA_DIR / "tc_factory_count_district_monthly.csv"


def load_factory_snapshot(district: str, csv_path: Path = FACTORY_PATH) -> dict[str, Any]:
    """取資料集最新一期該行政區工廠家數；缺資料／重複列絕不補零。"""
    unavailable: dict[str, Any] = {"available": False, "reason": "工廠快照不可用或資料不完整"}
    try:
        with Path(csv_path).open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not {"year_month", "district", "industry", "factories"}.issubset(reader.fieldnames):
                return unavailable
            rows = list(reader)
        if not rows:
            return unavailable
        latest = max(row["year_month"] for row in rows)
        current = [row for row in rows if row["year_month"] == latest and row["district"] == district]
        if not current:
            return {**unavailable, "period": latest}
        names = [row["industry"] for row in current]
        if not all(names) or len(names) != len(set(names)):
            return {**unavailable, "period": latest}
        counts = [(row["industry"], int(row["factories"])) for row in current]
        if any(count < 0 or str(count) != row["factories"].strip() for (_, count), row in zip(counts, current)):
            return {**unavailable, "period": latest}
    except (OSError, ValueError, KeyError, TypeError):
        return unavailable

    return {
        "available": True,
        "period": latest,
        "district": district,
        "factory_count": sum(count for _, count in counts),
        "category_count": len(counts),
        "top_industries": [
            {"industry": name, "factories": count}
            for name, count in sorted(counts, key=lambda item: (-item[1], item[0]))[:5]
        ],
        "source_name": "臺中市政府經濟發展局－臺中市工廠產業類別及行政區域家數",
        "source_url": FACTORY_SOURCE_URL,
        "grain": "臺中市行政區 × 工廠產業類別 × 月快照",
        "method": "取資料表最新月份、指定行政區的產業類別列，工廠家數加總；未跨月推估",
        "limitations": [
            "工廠登記家數不是職缺、缺工人數或擴廠計畫。",
            "歷史月份不連續，不能直接視為完整月度趨勢。",
            "本地匯入快照，並非每次查詢即時向官方重新下載。",
        ],
    }


def _selected(result: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """展示只保留統計量及證據，不回傳公司名稱或整份原始紀錄。"""
    if not result.get("available"):
        return result
    return {key: result[key] for key in keys if key in result}


def build_expansion_report(
    district: str,
    planned_hires: int,
    *,
    factory_path: Path = FACTORY_PATH,
) -> dict[str, Any]:
    factory = load_factory_snapshot(district, factory_path)
    company = _selected(get_gcis_new_company_trend("IND_MFG"), (
        "available", "latest_month", "latest_new_companies", "official_industry",
        "mapping_note", "missing_months", "complete_window_change_pct", "evidence",
    ))
    jobs = _selected(get_regional_job_demand(district, "IND_MFG"), (
        "available", "snapshot_date", "district", "industry_id", "retrieval_terms",
        "vacancy_postings", "requested_workers", "distinct_companies",
        "coverage_status", "limit_reached_districts", "excluded_location_records", "evidence",
    ))
    wage_result = get_wage_baseline("IND_MFG")
    if wage_result.get("available") and wage_result.get("average_insured_salary") is None:
        wage_result = {"available": False, "reason": "此期沒有可計算的平均投保薪資，不能將缺值當作 0"}
    wage = _selected(wage_result, (
        "available", "data_period", "region", "average_insured_salary", "metric_label", "evidence",
    ))
    items = [factory, company, jobs, wage]
    job_context = (
        f"{district}的台灣就業通 {jobs['snapshot_date']} 快照有 "
        f"{jobs['vacancy_postings']} 筆製造相關職務關鍵詞刊登；這是觀測到的招募需求，不是缺工人數。"
        if jobs.get("available") else "台灣就業通職缺快照目前不可用，不能把缺值當成零。"
    )
    factory_context = (
        f"{factory['period']} 的工廠快照有 {factory['factory_count']} 家，僅供產業分布參考。"
        if factory.get("available") else "工廠快照目前不可用，不能推估行政區工廠家數。"
    )
    return {
        "status": "ready" if all(item.get("available") for item in items) else (
            "partial" if any(item.get("available") for item in items) else "unavailable"
        ),
        "scenario": {"district": district, "planned_hires": planned_hires, "industry": "製造業"},
        "factory_snapshot": factory,
        "company_trend": company,
        "job_demand": jobs,
        "wage_baseline": wage,
        "interpretation": (
            f"你預計招募 {planned_hires} 人，這是你的規劃，不是官方觀測值。"
            f"{job_context}{factory_context}"
            "目前無法判定單一企業能否招到人；需補職務、薪資與招募時程，"
            "才能進一步評估招募風險。"
        ),
    }
