-- 區域產業 × 高教人才供需錯配預警系統 (System Spec v1.0)
-- 資料庫綱要 (SQLite DDL)

CREATE TABLE IF NOT EXISTS companies (
    company_id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    normalized_name TEXT,
    registration_date TEXT,
    status TEXT,
    capital INTEGER,
    city TEXT,
    district TEXT,
    address TEXT,
    primary_business_code TEXT,
    industry_id TEXT,
    change_date TEXT,
    has_capital_increase INTEGER DEFAULT 0,
    is_dissolved INTEGER DEFAULT 0,
    source TEXT DEFAULT 'GCIS_BATCH',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS industry_mapping_rules (
    business_code TEXT PRIMARY KEY,
    business_name TEXT,
    industry_id TEXT NOT NULL,
    industry_name TEXT NOT NULL,
    mapping_rule TEXT,
    version TEXT DEFAULT 'v1.0'
);

CREATE TABLE IF NOT EXISTS demographics_projection (
    academic_year INTEGER PRIMARY KEY,
    projected_age18_population INTEGER NOT NULL,
    national_freshmen_estimate INTEGER,
    source TEXT DEFAULT 'MOI_POPULATION'
);

CREATE TABLE IF NOT EXISTS industry_dynamics_mart (
    year INTEGER NOT NULL,
    district TEXT NOT NULL,
    industry_id TEXT NOT NULL,
    opening_count INTEGER NOT NULL,
    dissolution_count INTEGER NOT NULL,
    capital_increase_count INTEGER NOT NULL,
    beginning_stock INTEGER NOT NULL,
    ending_stock INTEGER NOT NULL,
    entry_rate REAL NOT NULL,
    capital_expansion_rate REAL NOT NULL,
    exit_rate REAL NOT NULL,
    source_version TEXT DEFAULT 'v1.0',
    updated_at TEXT,
    PRIMARY KEY (year, district, industry_id)
);

CREATE TABLE IF NOT EXISTS department_indicators_mart (
    academic_year INTEGER NOT NULL,
    institution_id TEXT NOT NULL,
    institution_name TEXT NOT NULL,
    department_id TEXT NOT NULL,
    department_name TEXT NOT NULL,
    enrolled_students INTEGER NOT NULL,
    freshmen_admitted INTEGER NOT NULL,
    registration_rate REAL NOT NULL,
    department_share REAL NOT NULL,
    projected_students_117 REAL NOT NULL,
    updated_at TEXT,
    PRIMARY KEY (academic_year, institution_id, department_id)
);

CREATE TABLE IF NOT EXISTS ucan_mapping_mart (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id TEXT NOT NULL,
    department_name TEXT NOT NULL,
    institution_id TEXT,
    institution_name TEXT,
    ucan_cluster_id TEXT NOT NULL,
    ucan_cluster_name TEXT NOT NULL,
    ucan_pathway_id TEXT NOT NULL,
    ucan_pathway_name TEXT NOT NULL,
    industry_id TEXT NOT NULL,
    industry_name TEXT NOT NULL,
    mapping_type TEXT NOT NULL,
    weight REAL NOT NULL,
    normalized_weight REAL NOT NULL,
    evidence TEXT NOT NULL,
    source TEXT NOT NULL,
    version TEXT DEFAULT 'v1.0'
);

CREATE TABLE IF NOT EXISTS industry_momentum_mart (
    industry_id TEXT PRIMARY KEY,
    industry_name TEXT NOT NULL,
    base_year INTEGER NOT NULL,
    entry_rate REAL NOT NULL,
    entry_trend REAL NOT NULL,
    capital_rate REAL NOT NULL,
    capital_trend REAL NOT NULL,
    exit_rate REAL NOT NULL,
    z_entry REAL NOT NULL,
    z_capital REAL NOT NULL,
    demand_momentum REAL NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS talent_supply_mart (
    industry_id TEXT PRIMARY KEY,
    industry_name TEXT NOT NULL,
    current_supply REAL NOT NULL,
    projected_supply_117 REAL NOT NULL,
    supply_growth REAL NOT NULL,
    supply_momentum REAL NOT NULL,
    total_contributing_depts INTEGER NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS mismatch_signal_mart (
    industry_id TEXT PRIMARY KEY,
    industry_name TEXT NOT NULL,
    demand_momentum REAL NOT NULL,
    supply_momentum REAL NOT NULL,
    mismatch REAL NOT NULL,
    mismatch_direction TEXT NOT NULL,
    mismatch_intensity REAL NOT NULL,
    warning_level TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_companies_district_industry ON companies (district, industry_id);
CREATE INDEX IF NOT EXISTS idx_dynamics_year_ind ON industry_dynamics_mart (year, industry_id);
CREATE INDEX IF NOT EXISTS idx_dept_lookup ON department_indicators_mart (institution_name, department_name);

-- A 級官方資料：台灣就業通當期職缺快照。
-- 這是「可觀測職缺樣本」，不是全體雇主或實際缺工人數。
CREATE TABLE IF NOT EXISTS official_job_vacancies (
    snapshot_date TEXT NOT NULL,
    record_id TEXT NOT NULL,
    district TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    occupation_title TEXT NOT NULL,
    occupation_major_code TEXT,
    occupation_major_name TEXT,
    occupation_minor_code TEXT,
    occupation_minor_name TEXT,
    openings INTEGER NOT NULL,
    work_location TEXT NOT NULL,
    salary_type TEXT,
    salary_lower REAL,
    salary_upper REAL,
    company_name TEXT,
    updated_date TEXT,
    application_deadline TEXT,
    source_url TEXT,
    source_dataset_id TEXT NOT NULL DEFAULT '44062',
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, record_id)
);

CREATE TABLE IF NOT EXISTS official_job_fetch_audit (
    snapshot_date TEXT NOT NULL,
    district TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    returned_count INTEGER NOT NULL,
    retained_count INTEGER NOT NULL,
    excluded_location_count INTEGER NOT NULL,
    query_limit INTEGER NOT NULL,
    limit_reached INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, district)
);

-- GCIS 公司登記新設家數：縣市 × 行業大類 × 月。
CREATE TABLE IF NOT EXISTS gcis_new_company_monthly (
    year_month TEXT NOT NULL,
    county TEXT NOT NULL,
    industry TEXT NOT NULL,
    new_companies INTEGER NOT NULL,
    new_capital_million_twd REAL,
    is_model_eligible INTEGER NOT NULL DEFAULT 1,
    source_dataset_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    loaded_at TEXT NOT NULL,
    PRIMARY KEY (year_month, county, industry)
);

-- 勞保局年末原始統計：地區 × 單位類別 × 行業大類 × 就保註記。
CREATE TABLE IF NOT EXISTS labor_insurance_baseline (
    data_period TEXT NOT NULL,
    region_code TEXT NOT NULL,
    region_name TEXT NOT NULL,
    unit_type_code TEXT NOT NULL,
    unit_type_name TEXT NOT NULL,
    industry_code TEXT NOT NULL,
    industry_name TEXT NOT NULL,
    employment_insurance_code TEXT NOT NULL,
    employment_insurance_name TEXT NOT NULL,
    insured_units INTEGER NOT NULL,
    insured_people INTEGER NOT NULL,
    average_insured_salary REAL NOT NULL,
    source_dataset_id TEXT NOT NULL DEFAULT '100999',
    source_url TEXT NOT NULL,
    loaded_at TEXT NOT NULL,
    PRIMARY KEY (
        data_period, region_code, unit_type_code,
        industry_code, employment_insurance_code
    )
);

CREATE INDEX IF NOT EXISTS idx_job_snapshot_district
    ON official_job_vacancies (snapshot_date, district);
CREATE INDEX IF NOT EXISTS idx_gcis_new_month_industry
    ON gcis_new_company_monthly (county, industry, year_month);
CREATE INDEX IF NOT EXISTS idx_labor_baseline_lookup
    ON labor_insurance_baseline (
        region_code, industry_code, unit_type_code,
        employment_insurance_code, data_period
    );
