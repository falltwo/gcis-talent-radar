"""Deterministic tools backed only by the approved government datasets."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from config import TARGET_INDUSTRIES
from database.db_manager import db
from engine.evidence_engine import build_evidence_object


TAIWANJOBS_URL = "https://data.gov.tw/dataset/44062"
GCIS_URL = "https://data.gcis.nat.gov.tw/od/detail?oid=01E5CFC6-9F09-4CB5-BE81-22B451E4B1BD"
LABOR_URL = "https://data.gov.tw/dataset/100999"

# TaiwanJobs publishes occupation fields rather than company industry codes.
# These versioned, explicit terms are therefore a transparent retrieval rule,
# not a claim that each vacancy's employer belongs to that industry.
JOB_RETRIEVAL_RULES: Dict[str, List[str]] = {
    "IND_MFG": ["製造", "機械", "機電", "cnc", "品管", "生產", "設備", "維修", "焊接", "車床", "銑床", "組裝", "模具"],
    "IND_ICT": ["軟體", "資訊", "程式", "系統", "網路", "資料", "數位", "ai", "工程師"],
    "IND_SEM": ["半導體", "電子", "光電", "晶圓", "封裝", "測試", "電機"],
    "IND_BIOMED": ["醫療", "醫事", "生技", "製藥", "護理", "照顧", "健康"],
    "IND_PRO_FIN": ["財務", "金融", "保險", "會計", "法務", "顧問", "管理"],
    "IND_TRADE_LOG": ["貿易", "物流", "倉儲", "運輸", "採購", "船務", "報關"],
    "IND_TOUR_CULT": ["觀光", "旅遊", "旅宿", "餐飲", "文創", "設計", "影音", "休閒"],
}

GCIS_INDUSTRY_MAP = {
    "IND_MFG": "製造業",
    "IND_SEM": "製造業",
    "IND_ICT": "資訊及通訊傳播業",
    "IND_BIOMED": "醫療保健及社會工作服務業",
    "IND_PRO_FIN": "專業科學及技術服務業",
    "IND_TRADE_LOG": "運輸及倉儲業",
    "IND_TOUR_CULT": "藝術娛樂及休閒服務業",
}

LABOR_INDUSTRY_MAP: Dict[str, List[str]] = {
    "IND_MFG": ["C"],
    "IND_SEM": ["C"],
    "IND_ICT": ["J"],
    "IND_BIOMED": ["Q"],
    "IND_PRO_FIN": ["K", "M"],
    "IND_TRADE_LOG": ["G", "H"],
    "IND_TOUR_CULT": ["I", "R"],
}


def _unsupported_industry(
    industry_id: Any,
    supported_industry_ids: Iterable[str],
) -> Dict[str, Any]:
    """Return an explicit failure instead of silently substituting an industry."""
    return {
        "available": False,
        "error_code": "UNSUPPORTED_INDUSTRY",
        "reason": f"不支援產業代碼：{industry_id}",
        "requested_industry_id": industry_id,
        "supported_industry_ids": sorted(supported_industry_ids),
    }


def _industry_name(industry_id: Optional[str]) -> Optional[str]:
    if not industry_id:
        return None
    return TARGET_INDUSTRIES.get(industry_id, {}).get("name", industry_id)


def _contains_any(record: Dict[str, Any], terms: Iterable[str]) -> bool:
    haystack = " ".join(
        str(record.get(key) or "")
        for key in ("occupation_title", "occupation_major_name", "occupation_minor_name")
    ).lower()
    return any(term.lower() in haystack for term in terms)


def get_regional_job_demand(
    district: Optional[str] = None,
    industry_id: Optional[str] = None,
    occupation_keyword: Optional[str] = None,
) -> Dict[str, Any]:
    if industry_id and industry_id not in JOB_RETRIEVAL_RULES:
        return _unsupported_industry(industry_id, JOB_RETRIEVAL_RULES)

    latest = db.fetch_one("SELECT MAX(snapshot_date) AS snapshot_date FROM official_job_vacancies")
    snapshot = latest.get("snapshot_date") if latest else None
    if not snapshot:
        return {
            "available": False,
            "reason": "尚未匯入台灣就業通官方快照",
            "required_action": "執行 python etl/load_official_labor_market.py --only jobs",
        }

    params: List[Any] = [snapshot]
    district_clause = ""
    if district:
        district_clause = " AND district = ?"
        params.append(district)
    rows = db.fetch_all(
        f"""
        SELECT * FROM official_job_vacancies
        WHERE snapshot_date = ? {district_clause}
        ORDER BY openings DESC, updated_date DESC
        """,
        tuple(params),
    )

    filters: List[str] = []
    if industry_id:
        terms = JOB_RETRIEVAL_RULES.get(industry_id, [])
        rows = [row for row in rows if _contains_any(row, terms)]
        filters.extend(terms)
    if occupation_keyword:
        keyword = occupation_keyword.strip().lower()
        rows = [row for row in rows if _contains_any(row, [keyword])]
        filters.append(occupation_keyword.strip())

    audit_params: List[Any] = [snapshot]
    audit_clause = ""
    if district:
        audit_clause = " AND district = ?"
        audit_params.append(district)
    audits = db.fetch_all(
        f"SELECT * FROM official_job_fetch_audit WHERE snapshot_date = ? {audit_clause}",
        tuple(audit_params),
    )
    capped = [row["district"] for row in audits if row["limit_reached"]]
    excluded = sum(int(row["excluded_location_count"]) for row in audits)
    total_openings = sum(int(row["openings"]) for row in rows)
    company_count = len({row["company_name"] for row in rows if row.get("company_name")})
    completeness = "QUERY_LIMIT_REACHED" if capped else "OBSERVED_SNAPSHOT_COMPLETE_WITHIN_QUERY_LIMIT"
    geography = f"台中市{district}" if district else "台中市 29 行政區"

    evidence = build_evidence_object(
        intent="JOB_DEMAND_QUERY",
        indicator_name="台灣就業通當期可觀測職缺",
        calculation_steps=[
            f"使用 {snapshot} 快照，依 3 碼郵遞區號逐區查詢",
            "僅保留工作地點明確符合該台中行政區的列",
            "需求人數為保留列的 JOB_PERSON 加總；職缺筆數為刊登紀錄數",
            "產業篩選使用公開職務名稱／職類欄位的版本化關鍵詞規則" if industry_id else "未套用產業關鍵詞規則",
        ],
        source_tables=["official_job_vacancies", "official_job_fetch_audit"],
        official_sources=["勞動部勞動力發展署－台灣就業通網站職缺清單"],
        data_period=snapshot,
        geography=geography,
        source_urls=[TAIWANJOBS_URL],
        dataset_ids=["44062"],
        limitations=[
            "這是當期公開職缺樣本，不是實際缺工人數或所有雇主母體。",
            "官方單次查詢上限為 1,000 筆；達上限的行政區不可視為完整總數。",
            "產業條件是職務文字檢索，不等同雇主的正式行業登記分類。",
            f"已排除 {excluded} 筆工作地點不明確符合查詢行政區的紀錄。",
        ],
        fetched_at=max((row["fetched_at"] for row in audits), default=snapshot),
    )
    return {
        "available": True,
        "snapshot_date": snapshot,
        "snapshot_year": int(snapshot[0:4]),
        "snapshot_month": int(snapshot[5:7]),
        "snapshot_day": int(snapshot[8:10]),
        "geography": geography,
        "district": district,
        "industry_id": industry_id,
        "industry_name": _industry_name(industry_id),
        "retrieval_terms": filters,
        "vacancy_postings": len(rows),
        "requested_workers": total_openings,
        "distinct_companies": company_count,
        "coverage_status": completeness,
        "query_limit": 1000,
        "limit_reached_districts": capped,
        "excluded_location_records": excluded,
        "top_vacancies": rows[:20],
        "evidence": evidence,
    }


def _complete_window_sum(values: Dict[str, int], end: pd.Period, months: int) -> Optional[int]:
    periods = pd.period_range(end=end, periods=months, freq="M")
    keys = [str(period) for period in periods]
    if any(key not in values for key in keys):
        return None
    return sum(values[key] for key in keys)


def get_gcis_new_company_trend(
    industry_id: str = "IND_MFG",
    months: int = 36,
) -> Dict[str, Any]:
    if industry_id not in GCIS_INDUSTRY_MAP:
        return _unsupported_industry(industry_id, GCIS_INDUSTRY_MAP)

    official_industry = GCIS_INDUSTRY_MAP[industry_id]
    rows = db.fetch_all(
        """
        SELECT year_month, county, industry, new_companies,
               new_capital_million_twd, source_dataset_id, source_url, loaded_at
        FROM gcis_new_company_monthly
        WHERE county = '臺中市' AND industry = ? AND is_model_eligible = 1
        ORDER BY year_month
        """,
        (official_industry,),
    )
    if not rows:
        return {
            "available": False,
            "reason": f"尚未匯入 GCIS『{official_industry}』月資料",
            "required_action": "執行 python etl/load_official_labor_market.py --only gcis",
        }

    months = max(1, min(int(months), 180))
    values = {row["year_month"]: int(row["new_companies"]) for row in rows}
    first = pd.Period(rows[0]["year_month"], freq="M")
    last = pd.Period(rows[-1]["year_month"], freq="M")
    expected = pd.period_range(first, last, freq="M")
    missing = [str(period) for period in expected if str(period) not in values]
    current_12 = _complete_window_sum(values, last, 12)
    previous_12 = _complete_window_sum(values, last - 12, 12)
    change_pct = None
    if current_12 is not None and previous_12 not in (None, 0):
        change_pct = round((current_12 / previous_12 - 1) * 100, 2)

    observed_last_12 = rows[-12:]
    latest = rows[-1]
    mapping_note = (
        "目標產業與 GCIS 官方行業大類相同"
        if industry_id == "IND_MFG"
        else f"{_industry_name(industry_id)}以 GCIS『{official_industry}』大類作為上位類別代理，不代表細產業家數"
    )
    evidence = build_evidence_object(
        intent="COMPANY_TREND_QUERY",
        indicator_name="GCIS 台中市公司新設月趨勢",
        calculation_steps=[
            "直接讀取 GCIS 每月新設登記家數，不使用 104 公司名稱反推或隨機生成",
            "排除 2010-12、2011-12 兩個孤立年末點；主序列自 2012-06 起",
            "近 12 個月與前 12 個月只有在各自月份完整時才計算年增率",
        ],
        source_tables=["gcis_new_company_monthly"],
        official_sources=["經濟部商工行政資料開放平臺－公司登記新設立家數及實收資本額按行業別及縣市別分"],
        data_period=f"{rows[0]['year_month']}～{rows[-1]['year_month']}",
        geography="臺中市（全市）",
        source_urls=[GCIS_URL],
        dataset_ids=["01E5CFC6-9F09-4CB5-BE81-22B451E4B1BD"],
        limitations=[
            "數值是當月新設公司，不是公司存量、職缺或實際缺工人數。",
            "資料粒度為臺中市全市 × 行業大類，不可下推到行政區或細產業。",
            f"官方序列缺月：{', '.join(missing) if missing else '無'}；缺月不補 0。",
            mapping_note,
        ],
        fetched_at=latest["loaded_at"],
    )
    return {
        "available": True,
        "industry_id": industry_id,
        "industry_name": _industry_name(industry_id),
        "official_industry": official_industry,
        "mapping_note": mapping_note,
        "period_start": rows[0]["year_month"],
        "period_end": rows[-1]["year_month"],
        "period_start_year": int(rows[0]["year_month"][0:4]),
        "period_start_month": int(rows[0]["year_month"][5:7]),
        "period_end_year": int(rows[-1]["year_month"][0:4]),
        "period_end_month": int(rows[-1]["year_month"][5:7]),
        "observation_count": len(rows),
        "missing_months": missing,
        "latest_month": latest["year_month"],
        "latest_year": int(latest["year_month"][0:4]),
        "latest_month_number": int(latest["year_month"][5:7]),
        "latest_new_companies": int(latest["new_companies"]),
        "comparison_window_months": 12,
        "observed_last_12_total": sum(int(row["new_companies"]) for row in observed_last_12),
        "complete_last_12_total": current_12,
        "complete_previous_12_total": previous_12,
        "complete_window_change_pct": change_pct,
        "history": rows[-months:],
        "evidence": evidence,
    }


def get_wage_baseline(industry_id: str = "IND_MFG") -> Dict[str, Any]:
    if industry_id not in LABOR_INDUSTRY_MAP:
        return _unsupported_industry(industry_id, LABOR_INDUSTRY_MAP)

    codes = LABOR_INDUSTRY_MAP[industry_id]
    placeholders = ",".join("?" for _ in codes)
    latest = db.fetch_one(
        """
        SELECT MAX(data_period) AS data_period
        FROM labor_insurance_baseline
        WHERE region_code = '66' AND unit_type_code = '1'
          AND employment_insurance_code = '1'
        """
    )
    period = latest.get("data_period") if latest else None
    if not period:
        return {
            "available": False,
            "reason": "尚未匯入勞保局年末統計",
            "required_action": "執行 python etl/load_official_labor_market.py --only labor",
        }

    rows = db.fetch_all(
        f"""
        SELECT * FROM labor_insurance_baseline
        WHERE data_period = ? AND region_code = '66'
          AND unit_type_code = '1' AND employment_insurance_code = '1'
          AND industry_code IN ({placeholders})
        ORDER BY industry_code
        """,
        tuple([period, *codes]),
    )
    if not rows:
        return {
            "available": False,
            "reason": f"勞保資料沒有行業代碼 {codes} 的核准口徑",
        }

    total_people = sum(int(row["insured_people"]) for row in rows)
    total_units = sum(int(row["insured_units"]) for row in rows)
    weighted_salary = (
        sum(float(row["average_insured_salary"]) * int(row["insured_people"]) for row in rows)
        / total_people
        if total_people else None
    )
    mapping_note = (
        f"使用勞保行業大類 {', '.join(row['industry_code'] for row in rows)}；"
        "若目標產業較細，此值只能作上位行業基線"
    )
    evidence = build_evidence_object(
        intent="WAGE_QUERY",
        indicator_name="臺中市勞工保險平均投保薪資基線",
        calculation_steps=[
            "限定地區代碼 66（臺中市）",
            "限定單位類別 1（產業勞工及交通公用事業之員工）",
            "限定單位就保註記 1（參加就保），避免不同口徑重複加總",
            "多個行業大類時，以月底投保人數加權平均投保薪資",
        ],
        source_tables=["labor_insurance_baseline"],
        official_sources=["勞動部勞工保險局－投保單位、人數及平均投保薪資原始統計資料"],
        data_period=period,
        geography="臺中市",
        source_urls=[LABOR_URL, *sorted({row["source_url"] for row in rows})],
        dataset_ids=["100999"],
        limitations=[
            "平均投保薪資是保險申報級距的統計平均，不等於實領薪資、職缺開薪或薪資中位數。",
            "目前資料是每年 12 月年末點，不是月度薪資序列。",
            mapping_note,
        ],
        fetched_at=max(row["loaded_at"] for row in rows),
    )
    return {
        "available": True,
        "industry_id": industry_id,
        "industry_name": _industry_name(industry_id),
        "data_period": period,
        "roc_year": int(period[0:3]),
        "month": int(period[3:5]),
        "region": "臺中市",
        "unit_type_code": "1",
        "employment_insurance_code": "1",
        "industry_codes": codes,
        "insured_units": total_units,
        "insured_people": total_people,
        "average_insured_salary": round(weighted_salary, 2) if weighted_salary is not None else None,
        "metric_label": "平均投保薪資（非實領薪資）",
        "mapping_note": mapping_note,
        "records": rows,
        "evidence": evidence,
    }
