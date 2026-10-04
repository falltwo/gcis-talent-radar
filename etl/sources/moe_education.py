"""
人才供給端（教育部）
- S1 高級中等學校科別資料（stats.moe.gov.tw/files/opendata/base2.csv，data.gov.tw/dataset/9617）
     臺中市各校 × 群別 × 科別 × 學年：各年級在學人數、上學年畢業生數
     → 一、二、三年級人數就是未來 3 年的畢業生管線（實測值，取代舊 repo 寫死的生源推估）
- S2 大專校院校務資訊公開平臺（UDB）學 1-1 在學學生數、學 2-1 畢業生數（以系所統計）
     原始檔沿用 repo 既有的 data/raw/moe_udb_cache/（原始專案下載，下載日未記錄）
     只取位於臺中市的 17 所大專校院

不做任何推估或補值：不再用「在學人數 ÷ 4」當新生數，也不補註冊率。
"""
import pandas as pd

from etl.sources.common import RAW_DATA_DIR, fetch, read_csv_bytes, session, write_processed

VOC_URL = "https://stats.moe.gov.tw/files/opendata/base2.csv"
VOC_RAW = RAW_DATA_DIR / "moe_vocational" / "base2.csv"
UDB = RAW_DATA_DIR / "moe_udb_cache"
UDB_ENROLLED = UDB / "學1-1.正式學籍在學學生人數-以「系(所)」統計.csv"
UDB_GRADUATES = UDB / "學2-1.畢業生數及其取得輔系、雙主修資格人數-以「系(所)」統計.csv"
TAICHUNG_UNIVERSITIES = [
    "國立中興大學", "國立臺中教育大學", "國立臺中科技大學", "國立勤益科技大學", "國立臺灣體育運動大學",
    "東海大學", "逢甲大學", "靜宜大學", "亞洲大學", "中國醫藥大學", "中山醫學大學", "朝陽科技大學",
    "弘光科技大學", "嶺東科技大學", "中臺科技大學", "僑光科技大學", "修平學校財團法人修平科技大學",
]
GRADE_COLS = {1: ("一年級男學生數", "一年級女學生數"), 2: ("二年級男學生數", "二年級女學生數"),
              3: ("三年級男學生數", "三年級女學生數"), 4: ("四年級男學生數", "四年級女學生數")}


def fetch_all():
    fetch(session(), "moe_vocational", VOC_URL, VOC_RAW, min_bytes=100_000, force=False)


def _n(s):
    return pd.to_numeric(s, errors="coerce")


def transform_vocational():
    d = read_csv_bytes(VOC_RAW.read_bytes(), dtype=str)
    d = d[d["縣市名稱"] == "臺中市"].copy()
    out = pd.DataFrame({
        "academic_year": d["學年度"].astype(int), "school_code": d["學校代碼"], "school": d["學校名稱"],
        "level": d["等級名稱"], "day_night": d["日夜別名稱"], "group": d["群別名稱"], "dept_code": d["科系代碼"],
        "dept": d["科系名稱"]})
    for g, (m, f) in GRADE_COLS.items():
        out[f"grade{g}_students"] = _n(d[m]).fillna(0) + _n(d[f]).fillna(0)
    out["graduates_prev_year"] = _n(d["上學年畢業生數男"]).fillna(0) + _n(d["上學年畢業生數女"]).fillna(0)
    out = out[~out["level"].isin(["附設國中部"])]   # 國中部不是高中職供給
    write_processed(out.reset_index(drop=True), "tc_vocational_dept_annual",
                    sources=["教育部統計處 高級中等學校科別資料", VOC_URL],
                    grain="臺中市 × 學校 × 等級（普通科／專業群科／綜合高中／實用技能／進修部）× 群別 × 科別 × 學年",
                    notes=["已排除附設國中部",
                           "grade1–3_students：下一、二、三學年度的畢業生管線（不含轉學、休退學損耗）",
                           "graduates_prev_year：該學年度資料所列的『上學年』畢業生數",
                           "學校所在地為臺中市，學生不一定留在臺中就業"])
    return out


def _udb(path, value_col, value_name):
    d = read_csv_bytes(path.read_bytes(), dtype=str)
    d = d[d["學校名稱"].isin(TAICHUNG_UNIVERSITIES)]
    return pd.DataFrame({
        "academic_year": d["學年度"].astype(int), "school": d["學校名稱"], "school_type": d["學校類別"],
        "dept_code": d["系所代碼"], "dept": d["系所名稱"], "program": d["學制班別"],
        value_name: _n(d[value_col])})


def transform_udb():
    enrolled = _udb(UDB_ENROLLED, "在學學生數小計", "enrolled")
    grads = _udb(UDB_GRADUATES, "畢業生數小計", "graduates")
    key = ["academic_year", "school", "school_type", "dept_code", "dept", "program"]
    df = enrolled.groupby(key, as_index=False)["enrolled"].sum(min_count=1).merge(
        grads.groupby(key, as_index=False)["graduates"].sum(min_count=1), on=key, how="outer")
    found = sorted(df["school"].unique())
    missing = sorted(set(TAICHUNG_UNIVERSITIES) - set(found))
    write_processed(df.sort_values(key).reset_index(drop=True), "tc_udb_dept_annual",
                    sources=["教育部 大專校院校務資訊公開平臺 學1-1 在學學生數、學2-1 畢業生數（以系所統計）",
                             "原始檔：data/raw/moe_udb_cache/（沿用原始專案下載檔）"],
                    grain="臺中市 17 所大專 × 系所 × 學制班別 × 學年",
                    notes=[f"在學：{enrolled.academic_year.min()}–{enrolled.academic_year.max()} 學年；"
                           f"畢業：{grads.academic_year.min()}–{grads.academic_year.max()} 學年",
                           f"清單內但資料中沒有的學校：{missing or '無'}",
                           "系所代碼前碼對應教育部學科標準分類；系所 → 職類的對照尚未建立"])
    return df


def transform():
    transform_vocational()
    transform_udb()


if __name__ == "__main__":
    fetch_all()
    transform()
