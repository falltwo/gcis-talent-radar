"""
B1／E3：勞工保險投保單位、人數及平均投保薪資原始統計資料（勞動部勞工保險局，data.gov.tw/dataset/100999）
每年只公開 12 月一期（107–114 年），粒度：縣市 × 單位類別 × 業別（行業大類）× 就保註記。

輸出 tc_labor_insurance_annual（只取臺中市，地區別代碼 66）
- employee_scope：受僱者口徑＝單位類別 1 產業勞工、5 公司行號員工、8 其他事業員工；
  2 職業勞工（工會加保、無一定雇主）、4 政府機關學校、7 自願投保等不算受僱於事業單位的員工
- 平均投保薪資 ≠ 實領薪資（有投保級距上限）
"""
import pandas as pd

from etl.sources.common import RAW_DATA_DIR, fetch, read_csv_bytes, session, write_processed

DATASET = "https://data.gov.tw/dataset/100999"
CODEBOOK = "https://apiservice.mol.gov.tw/OdService/download/A17000000J-030212-2Au"
YEAR_CSV = [   # 107–114 年 12 月，各一份 CSV（資料集頁面依序列出）
    "https://apiservice.mol.gov.tw/OdService/download/A17000000J-030212-Oe8",
    "https://apiservice.mol.gov.tw/OdService/download/A17000000J-030212-oa3",
    "https://apiservice.mol.gov.tw/OdService/download/A17000000J-030212-xZg",
    "https://apiservice.mol.gov.tw/OdService/download/A17000000J-030212-qrD",
    "https://apiservice.mol.gov.tw/OdService/download/A17000000J-030212-QGf",
    "https://apiservice.mol.gov.tw/OdService/download/A17000000J-030212-lqe",
    "https://apiservice.mol.gov.tw/OdService/download/A17000000J-030212-mgv",
    "https://apiservice.mol.gov.tw/OdService/download/A17000000J-030212-W96",
]
RAW = RAW_DATA_DIR / "labor_insurance"
TAICHUNG_CODE = "66"
EMPLOYEE_UNIT_TYPES = {"1", "5", "8"}


def fetch_all():
    s = session()
    fetch(s, "labor_insurance", CODEBOOK, RAW / "codebook.csv")
    for i, url in enumerate(YEAR_CSV):
        fetch(s, "labor_insurance", url, RAW / f"resource_{i:02d}.csv", min_bytes=1000)


def transform():
    code = read_csv_bytes((RAW / "codebook.csv").read_bytes(), dtype=str)
    names = {(r["統計項目"], r["代號"]): r["對照中文名稱"] for _, r in code.iterrows()}
    frames = []
    for p in sorted(RAW.glob("resource_*.csv")):
        df = read_csv_bytes(p.read_bytes(), dtype=str)
        df = df[df["地區別"].str.zfill(2) == TAICHUNG_CODE]
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({
        "year_month": df["資料年月"].str[:3].astype(int).add(1911).astype(str) + "-" + df["資料年月"].str[3:],
        "industry_code": df["業別"],
        "industry": [names.get(("業別", c), c) for c in df["業別"]],
        "unit_type_code": df["單位類別"],
        "unit_type": [names.get(("單位類別", c), c) for c in df["單位類別"]],
        "employment_insurance_flag": df["單位就保註記"],
        "employee_scope": df["單位類別"].isin(EMPLOYEE_UNIT_TYPES),
    })
    for src, dst in [("本月底單位數", "units"), ("本月底投保人數", "insured"), ("本月加保投保人數", "insured_added"),
                     ("本月退保投保人數", "insured_withdrawn"), ("平均投保薪資", "avg_insured_wage")]:
        out[dst] = pd.to_numeric(df[src], errors="coerce")
    out = out.sort_values(["industry_code", "year_month", "unit_type_code"]).reset_index(drop=True)
    mfg = out[(out.industry_code == "C") & out.employee_scope].groupby("year_month")["insured"].sum()
    write_processed(out, "tc_labor_insurance_annual", sources=["勞動部勞工保險局 勞工保險投保單位、人數及平均投保薪資原始統計資料", DATASET],
                    grain="臺中市 × 行業大類 × 單位類別 × 就保註記 × 年（每年 12 月）",
                    notes=["employee_scope=True：產業勞工、公司行號員工、其他事業員工；職業勞工不算",
                           f"臺中製造業受僱者口徑投保人數（12 月）：{mfg.astype(int).to_dict()}",
                           "加保、退保人數只是 12 月單月流量，不是全年",
                           "平均投保薪資 ≠ 實領薪資"])
    return out


if __name__ == "__main__":
    fetch_all()
    transform()
