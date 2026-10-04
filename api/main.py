"""
FastAPI Backend Application
區域產業 × 高教人才供需錯配預警系統 (System Specification v1.0)
"""
import sys
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    BASE_DIR, TARGET_CITY, TAICHUNG_DISTRICTS, TARGET_INDUSTRIES,
    HISTORICAL_YEARS, BASE_ACADEMIC_YEAR, TARGET_PROJECTION_YEAR
)
from database.db_manager import db
from agent.audit_log import AuditLogError
from agent.agent_service import OpenRouterError, agent_service
from engine.gcis_live_verifier import verify_company_live
from engine.official_labor_market import (
    get_gcis_new_company_trend,
    get_regional_job_demand,
    get_wage_baseline,
)
from tests.test_etl_quality import run_data_quality_audit
from benchmark.run_benchmark import run_benchmark_validation

app = FastAPI(
    title="Regional Industry-Talent Structural Mismatch Early-Warning System",
    description="台中市區域產業動能 × 高教人才供給結構性錯配預警系統 (System Spec v1.0)",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Data Models -----------------
class ChatRequest(BaseModel):
    query: str

class VerifyRequest(BaseModel):
    query: str


OFFICIAL_DATA_REFRESH_QUERIES = {
    "official_job_vacancies": "SELECT MAX(fetched_at) AS refreshed_at FROM official_job_vacancies",
    "gcis_new_company_monthly": "SELECT MAX(loaded_at) AS refreshed_at FROM gcis_new_company_monthly",
    "labor_insurance_baseline": "SELECT MAX(loaded_at) AS refreshed_at FROM labor_insurance_baseline",
}

DERIVED_MART_BUILD_QUERIES = {
    "industry_momentum_mart": "SELECT MAX(updated_at) AS refreshed_at FROM industry_momentum_mart",
    "talent_supply_mart": "SELECT MAX(updated_at) AS refreshed_at FROM talent_supply_mart",
    "mismatch_signal_mart": "SELECT MAX(updated_at) AS refreshed_at FROM mismatch_signal_mart",
}

UNVERIFIED_LEGACY_TIMESTAMP_QUERIES = {
    "companies": "SELECT MAX(updated_at) AS refreshed_at FROM companies",
    "industry_dynamics_mart": "SELECT MAX(updated_at) AS refreshed_at FROM industry_dynamics_mart",
    "department_indicators_mart": "SELECT MAX(updated_at) AS refreshed_at FROM department_indicators_mart",
}


def _get_recorded_times(queries: Dict[str, str]) -> Dict[str, Optional[str]]:
    refresh_times: Dict[str, Optional[str]] = {}
    for dataset, sql in queries.items():
        row = db.fetch_one(sql)
        refresh_times[dataset] = row.get("refreshed_at") if row else None
    return refresh_times


def get_dataset_refresh_times() -> Dict[str, Optional[str]]:
    """Return official source fetch/load timestamps only."""
    return _get_recorded_times(OFFICIAL_DATA_REFRESH_QUERIES)

# ----------------- API Endpoints -----------------

@app.get("/api/overview")
def get_overview() -> Dict[str, Any]:
    """Page 1: Overview Dashboard Metrics"""
    official_refresh_times = get_dataset_refresh_times()
    derived_mart_build_times = _get_recorded_times(DERIVED_MART_BUILD_QUERIES)
    unverified_legacy_timestamps = _get_recorded_times(UNVERIFIED_LEGACY_TIMESTAMP_QUERIES)
    recorded_official_times = [value for value in official_refresh_times.values() if value]
    comp_count = db.fetch_all("SELECT COUNT(*) as c FROM companies")[0]["c"]
    dept_count = db.fetch_all("SELECT COUNT(DISTINCT department_name) as c FROM department_indicators_mart WHERE academic_year = 113")[0]["c"]
    school_count = db.fetch_all("SELECT COUNT(DISTINCT institution_name) as c FROM department_indicators_mart WHERE academic_year = 113")[0]["c"]
    
    # Mismatch summary
    mismatch_rows = db.fetch_all("SELECT * FROM mismatch_signal_mart ORDER BY mismatch_intensity DESC")
    high_warnings = [r for r in mismatch_rows if r["warning_level"] == "High"]
    med_warnings = [r for r in mismatch_rows if r["warning_level"] == "Medium"]
    
    # Total stock at 113
    total_stock_113 = db.fetch_all("SELECT SUM(ending_stock) as s FROM industry_dynamics_mart WHERE year = 113")[0]["s"]
    
    return {
        "status": "success",
        "city": TARGET_CITY,
        "total_companies_registered": int(total_stock_113),
        "verified_sample_companies": int(comp_count),
        "target_industries_count": len(TARGET_INDUSTRIES),
        "monitored_departments_count": int(dept_count),
        "partner_universities_count": int(school_count),
        "data_period": "產業登記：109-113年 ｜ 高教推估：109-117學年度",
        "last_updated": max(recorded_official_times) if recorded_official_times else None,
        "last_updated_type": "OFFICIAL_SOURCE_FETCH_OR_LOAD",
        "last_updated_scope": "latest official source fetch/load timestamp; excludes derived mart build times",
        "dataset_refresh_times": official_refresh_times,
        "derived_mart_build_times": derived_mart_build_times,
        "derived_mart_build_times_note": "Build times describe local computation only and do not imply that official sources were refreshed then.",
        "unverified_legacy_dataset_timestamps": unverified_legacy_timestamps,
        "high_warning_count": len(high_warnings),
        "medium_warning_count": len(med_warnings),
        "mismatch_signals": mismatch_rows
    }

@app.get("/api/industry-dynamics")
def get_industry_dynamics(
    industry_id: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    district: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Page 2: Industry Dynamics Filterable Query"""
    conditions = []
    params = []

    if industry_id and industry_id != "ALL":
        conditions.append("industry_id = ?")
        params.append(industry_id)
    if year and year != 0:
        conditions.append("year = ?")
        params.append(year)
    if district and district != "ALL":
        conditions.append("district = ?")
        params.append(district)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"""
        SELECT 
            year, district, industry_id,
            SUM(opening_count) as opening_count,
            SUM(dissolution_count) as dissolution_count,
            SUM(capital_increase_count) as capital_increase_count,
            SUM(beginning_stock) as beginning_stock,
            SUM(ending_stock) as ending_stock
        FROM industry_dynamics_mart
        {where_clause}
        GROUP BY year, industry_id
        ORDER BY year ASC, industry_id ASC
    """
    rows = db.fetch_all(sql, tuple(params))

    # Calculate actual rates
    enriched = []
    for r in rows:
        beg = r["beginning_stock"]
        e_rate = round(r["opening_count"] / beg * 100, 2) if beg > 0 else 0.0
        c_rate = round(r["capital_increase_count"] / beg * 100, 2) if beg > 0 else 0.0
        x_rate = round(r["dissolution_count"] / beg * 100, 2) if beg > 0 else 0.0
        ind_info = TARGET_INDUSTRIES.get(r["industry_id"], {})
        enriched.append({
            **r,
            "industry_name": ind_info.get("name", r["industry_id"]),
            "entry_rate_pct": e_rate,
            "capital_expansion_rate_pct": c_rate,
            "exit_rate_pct": x_rate
        })

    # Also return momentum table
    mom_table = db.fetch_all("SELECT * FROM industry_momentum_mart ORDER BY demand_momentum DESC")
    return {
        "status": "success",
        "filters": {"industry_id": industry_id, "year": year, "district": district},
        "records": enriched,
        "momentum_summary": mom_table
    }

@app.get("/api/spatial-demand")
def get_spatial_demand(district: Optional[str] = Query(None), year: int = 113) -> Dict[str, Any]:
    """Page 3: Taichung Industry Map (Demand-side spatial metrics)"""
    if district and district != "ALL":
        sql = """
            SELECT industry_id, opening_count, dissolution_count, capital_increase_count, ending_stock, entry_rate, capital_expansion_rate, exit_rate
            FROM industry_dynamics_mart
            WHERE district = ? AND year = ?
            ORDER BY ending_stock DESC
        """
        rows = db.fetch_all(sql, (district, year))
        enriched = []
        for r in rows:
            enriched.append({
                **r,
                "industry_name": TARGET_INDUSTRIES.get(r["industry_id"], {}).get("name", r["industry_id"])
            })
        return {
            "status": "success",
            "district": district,
            "year": year,
            "industries": enriched
        }

    # Aggregate by all 29 districts
    sql = """
        SELECT district, SUM(ending_stock) as total_stock, SUM(opening_count) as total_openings, SUM(capital_increase_count) as total_cap_inc
        FROM industry_dynamics_mart
        WHERE year = ?
        GROUP BY district
        ORDER BY total_stock DESC
    """
    rows = db.fetch_all(sql, (year,))
    return {
        "status": "success",
        "year": year,
        "districts": rows,
        "allowed_districts": TAICHUNG_DISTRICTS
    }

@app.get("/api/talent-supply")
def get_talent_supply_view() -> Dict[str, Any]:
    """Page 4: Talent Supply Projections & UCAN Mappings"""
    supply_rows = db.fetch_all("SELECT * FROM talent_supply_mart ORDER BY supply_momentum DESC")
    demo_rows = db.fetch_all("SELECT * FROM demographics_projection ORDER BY academic_year ASC")
    
    # Top departments contributing to supply
    top_depts = db.fetch_all("""
        SELECT d.institution_name, d.department_name, u.industry_name, d.enrolled_students, d.projected_students_117, u.normalized_weight
        FROM department_indicators_mart d
        INNER JOIN ucan_mapping_mart u ON d.department_name = u.department_name AND d.institution_name = u.institution_name
        WHERE d.academic_year = 113
        ORDER BY d.enrolled_students DESC
        LIMIT 25
    """)
    
    return {
        "status": "success",
        "target_year": TARGET_PROJECTION_YEAR,
        "base_year": BASE_ACADEMIC_YEAR,
        "industry_supply": supply_rows,
        "demographics": demo_rows,
        "top_contributing_departments": top_depts
    }

@app.get("/api/mismatch")
def get_mismatch_view() -> Dict[str, Any]:
    """Page 5: Core Mismatch Monitor (Quadrant Plot data & signals)"""
    rows = db.fetch_all("SELECT * FROM mismatch_signal_mart ORDER BY mismatch_intensity DESC")
    quadrants = {
        "Q1_Expanding_Both": [],  # High Demand, High Supply
        "Q2_Shortage_Risk": [],   # High Demand, Low Supply (Crucial Risk!)
        "Q3_Contracting_Both": [],# Low Demand, Low Supply
        "Q4_Surplus_Pressure": [] # Low Demand, High Supply
    }

    formatted = []
    for r in rows:
        d = float(r["demand_momentum"])
        s = float(r["supply_momentum"])
        ev = json.loads(r["evidence_json"])
        
        # Quadrant classification
        if d >= 0 and s >= 0:
            quad_label = "第一象限：雙重擴張（供需熱絡）"
            quad_key = "Q1_Expanding_Both"
        elif d >= 0 and s < 0:
            quad_label = "第二象限：嚴重短缺風險（產業擴張×供給緊縮）"
            quad_key = "Q2_Shortage_Risk"
        elif d < 0 and s < 0:
            quad_label = "第三象限：雙重收縮（產業趨緩×人才分流）"
            quad_key = "Q3_Contracting_Both"
        else:
            quad_label = "第四象限：相對過剩壓力（產業收縮×供給充裕）"
            quad_key = "Q4_Surplus_Pressure"

        item = {
            "industry_id": r["industry_id"],
            "industry_name": r["industry_name"],
            "demand_momentum": d,
            "supply_momentum": s,
            "mismatch": float(r["mismatch"]),
            "intensity": float(r["mismatch_intensity"]),
            "warning_level": r["warning_level"],
            "direction": r["mismatch_direction"],
            "quadrant": quad_label,
            "quadrant_key": quad_key,
            "color": TARGET_INDUSTRIES.get(r["industry_id"], {}).get("color", "#64748B"),
            "drivers": ev.get("drivers", {}),
            "evidence": ev
        }
        formatted.append(item)
        quadrants[quad_key].append(item)

    return {
        "status": "success",
        "mismatch_signals": formatted,
        "quadrant_groups": quadrants
    }

@app.post("/api/agent/chat")
def agent_chat(req: ChatRequest) -> Dict[str, Any]:
    """Keyword scope and fair-hiring guards, OpenRouter tool-calling, and audit logging."""
    try:
        return agent_service.process_query(req.query)
    except (OpenRouterError, AuditLogError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.post("/api/agent/verify-company")
def verify_company_api(req: VerifyRequest) -> Dict[str, Any]:
    """Tool: GCIS Single Company Verification"""
    res = verify_company_live(req.query)
    return res


def _raise_official_tool_error(result: Dict[str, Any]) -> None:
    status_code = 400 if result.get("error_code") == "UNSUPPORTED_INDUSTRY" else 503
    raise HTTPException(status_code=status_code, detail=result)


@app.get("/api/official/job-demand")
def official_job_demand(
    district: Optional[str] = Query(None),
    industry_id: Optional[str] = Query(None),
    occupation_keyword: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Approved tool: current TaiwanJobs observable vacancy snapshot."""
    if district and district not in TAICHUNG_DISTRICTS:
        raise HTTPException(status_code=400, detail="district 必須是台中市 29 行政區之一")
    result = get_regional_job_demand(district, industry_id, occupation_keyword)
    if not result.get("available"):
        _raise_official_tool_error(result)
    return result

@app.get("/api/official/company-trend")
def official_company_trend(
    industry_id: str = Query("IND_MFG"),
    months: int = Query(36, ge=1, le=180),
) -> Dict[str, Any]:
    """Approved tool: GCIS monthly new-company trend at city/industry-major level."""
    result = get_gcis_new_company_trend(industry_id, months)
    if not result.get("available"):
        _raise_official_tool_error(result)
    return result

@app.get("/api/official/wage-baseline")
def official_wage_baseline(
    industry_id: str = Query("IND_MFG"),
) -> Dict[str, Any]:
    """Approved tool: BLI average insured-salary baseline (not take-home pay)."""
    result = get_wage_baseline(industry_id)
    if not result.get("available"):
        _raise_official_tool_error(result)
    return result

@app.get("/api/quality-report")
def get_quality_report() -> Dict[str, Any]:
    """Section 31: ETL Quality Report"""
    rep_path = BASE_DIR / "reports" / "etl_quality_report.json"
    if rep_path.exists():
        with open(rep_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return run_data_quality_audit()

@app.get("/api/benchmark/summary")
def get_benchmark_summary() -> Dict[str, Any]:
    """Section 29 & 30: Benchmark Evaluation Results"""
    rep_path = BASE_DIR / "reports" / "benchmark_accuracy_report.json"
    if rep_path.exists():
        with open(rep_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return run_benchmark_validation()

# ----------------- Frontend Web Serving -----------------
UI_DIR = BASE_DIR / "ui"
STATIC_DIR = UI_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
def serve_frontend():
    index_file = UI_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Regional Industry-Talent Mismatch System API is running. Build index.html next."}

@app.get("/architecture")
@app.get("/architecture/index.html")
@app.get("/ui/architecture.html")
def serve_architecture():
    arch_file = BASE_DIR / "architecture" / "index.html"
    if arch_file.exists():
        return FileResponse(arch_file)
    return {"error": "architecture/index.html not found"}

if __name__ == "__main__":
    import uvicorn
    print("Starting FastAPI Local Server on http://127.0.0.1:8000 ...")
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=False)
