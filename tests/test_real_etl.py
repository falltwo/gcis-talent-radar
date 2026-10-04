"""
真實資料 ETL 的驗收測試（讀 data/processed/ 的產出）：python -m pytest tests/test_real_etl.py -q
裡面的數字都是人工對過原始來源的（PDF、官方查詢頁、原始 CSV），ETL 改壞了這些測試會失敗。
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PROCESSED_DATA_DIR
from etl.quality import KEYS
from etl.sources.common import PII_PATTERN


def load(name):
    p = PROCESSED_DATA_DIR / f"{name}.csv"
    if not p.exists():
        pytest.skip(f"{name} 尚未產生，先跑 python -m etl.run_real_etl")
    return pd.read_csv(p, dtype={"industry_code": str}, low_memory=False)


@pytest.mark.parametrize("name", list(KEYS))
def test_no_pii_and_unique_keys(name):
    df = load(name)
    assert not [c for c in df.columns if PII_PATTERN.search(str(c))]
    if KEYS[name]:
        assert not df.duplicated(KEYS[name]).any()


def test_gcis_missing_months_recovered_from_official_source():
    df = load("tc_company_by_industry_monthly")
    mfg = df[(df.industry == "製造業") & (df.metric == "new")].set_index("year_month")
    assert mfg.loc["2025-08", "companies"] == 91
    assert mfg.loc["2025-09", "companies"] == 75
    assert (mfg.loc[["2025-08", "2025-09"], "quality_flag"] == "official_monthly_recovered").all()
    assert mfg.loc["2026-08", "companies"] == 75          # 組員交接文件記載值
    assert (mfg.loc["2010-12", "quality_flag"]) == "isolated_before_series"


def test_jobmarket_matches_pdf_table1():
    df = load("tc_jobmarket_monthly").set_index("period")
    # 113Q2 表 1（組員轉錄、本次 PDF 逐格核對）
    assert df.loc["2024-04", "new_seekers"] == 5686 and df.loc["2024-04", "new_openings"] == 9806
    assert df.loc["2024-06", "openings_per_seeker"] == 1.38
    # 109Q4 月份欄折行（10 → 「1」「0」）仍要對到正確月份
    assert df.loc["2020-10", "new_seekers"] == 3556 and df.loc["2020Q4", "new_seekers"] == 10264
    months = df[~df.is_quarter_total.astype(bool)]
    assert len(months) == 78


def test_jobmarket_occupation_complete():
    df = load("tc_jobmarket_occupation_q")
    assert (df.groupby(["roc_year", "quarter"]).size() == 9).all()
    q = df[(df.roc_year == 115) & (df.quarter == 2)].set_index("occupation")
    assert q.loc["機械設備操作及組裝人員", "openings_per_seeker"] == 1.67


def test_ee520_reproduces_official_query():
    df = load("tc_factory_district_industry_annual")
    d = df[(df.district == "大雅區") & (df.industry_code == "29")].set_index("roc_year")
    assert d.loc[[111, 112, 113], "factories"].tolist() == [207, 211, 219]
    assert d.loc[[111, 112, 113], "employees"].tolist() == [5771, 5646, 5644]
    assert df.district.nunique() == 29 and df.industry_code.nunique() == 26


def test_labor_insurance_unit_types():
    df = load("tc_labor_insurance_annual")
    c = df[(df.industry_code == "C") & (df.year_month == "2025-12")]
    assert c.loc[c.unit_type_code.astype(str) == "1", "insured"].sum() == 361509
    assert c.loc[c.employee_scope, "insured"].sum() == 375993    # 不含職業勞工


def test_vocational_excludes_junior_high():
    df = load("tc_vocational_dept_annual")
    assert "附設國中部" not in set(df.level)
    assert df.academic_year.max() >= 114
