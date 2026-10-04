"""
臺中市政府資料開放平臺（經濟發展局）
- C1  臺中市工廠產業類別及行政區域家數（data.gov.tw/dataset/174209）：月快照，行政區 × 產業類別
- B4  臺中市製造業工廠校正暨營運調查統計（data.gov.tw/dataset/175730）：年，全市 × 製造業中類
      （注意：欄位「行政區域代碼」是機關所在地，不是分區資料）

兩者原檔都是「地區、項目、欄位名稱、數值、資料時間日期」的長表 JSON，另含機關聯絡電話、Email 欄位（不保留）。
"""
import json

import pandas as pd

from etl.sources.common import RAW_DATA_DIR, fetch, session, write_processed

BASE = "https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid="
FACTORY_COUNT_RIDS = [
    "4680d868-a632-499a-8e19-e172d327ad4c", "ddba787b-5945-4edf-897e-56e9f05ce5e1", "24e4f44a-7228-4705-ae8d-73aa5c8e86c8",
    "1e006dc3-4e43-484f-9f4e-ae628ed7b41f", "0dbbc20b-4056-43cc-9659-535fc7da060b", "05e9ee38-20fd-4849-ab08-ce75e375b690",
    "231e74d9-15d3-41ac-bb08-96ecea62f6e5", "c8beb972-f538-4879-86e2-d2f0e0e35997", "b9e23d81-8a7f-4ba9-aa8f-65e51cceeb65",
    "de20c23f-96af-4ec9-93d5-2b755a819c62", "48a71a28-bb23-4118-b2e4-20a4b51bc4fe", "47c86ff7-fab0-4f65-b86e-6c7916aacbd4",
    "0180775b-a5d5-4f50-b19c-ede0f520eda1", "1a703e1a-9da1-4f6f-bbb6-f47715659773", "ef7e1822-3935-4f64-b4d8-0d343fa370a9",
    "7ac945db-229d-45a2-8b59-f68099bff6c5", "864aa627-2200-4fb0-8bb2-826bfc645dbc", "7b2fbfa8-27be-4bc1-88ca-5d49fc252d55",
]
FACTORY_SURVEY_RIDS = [
    "ca55c22e-2384-48e8-9714-c2cd72155c1d", "98c3a551-3799-4e4a-880c-3b16f0e88c76", "c61551ed-0eee-4864-a4b5-f3d19fcd7887",
    "f6dfbf35-62a5-4d71-a63e-0d9786b49762", "1ae4a9c0-c9a1-45cf-8a8e-1ff6b477d12d", "bac7939a-a9e5-4069-8b94-f42a0bb21a99",
    "8329f0a9-b237-4f50-a6ec-fc6c5b7238fa",
]
RAW = RAW_DATA_DIR / "taichung_opendata"


def fetch_all():
    s = session()
    for name, rids in [("factory_count", FACTORY_COUNT_RIDS), ("factory_survey", FACTORY_SURVEY_RIDS)]:
        for rid in rids:
            fetch(s, f"taichung_{name}", BASE + rid, RAW / name / f"{rid}.json", min_bytes=500)


def _load(name):
    rows = []
    for p in sorted((RAW / name).glob("*.json")):
        data = json.loads(p.read_bytes().decode("utf-8-sig"))
        for r in data:
            rows.append({"area": r["地區"], "item": r["項目"], "field": r["欄位名稱"],
                         "value": pd.to_numeric(r["數值"], errors="coerce"), "date": r["資料時間日期"][:10]})
    return pd.DataFrame(rows).drop_duplicates()


def transform():
    fc = _load("factory_count")
    fc = fc.assign(year_month=fc["date"].str[:7], district=fc["area"].str.replace("臺中市", "", regex=False),
                   industry=fc["field"]).rename(columns={"value": "factories"})
    fc = fc[["year_month", "district", "industry", "factories"]].sort_values(["year_month", "district", "industry"])
    months = sorted(fc.year_month.unique())
    write_processed(fc, "tc_factory_count_district_monthly",
                    sources=["臺中市政府經濟發展局 臺中市工廠產業類別及行政區域家數", "https://data.gov.tw/dataset/174209"],
                    grain="臺中市行政區 × 工廠產業類別 × 月（快照）",
                    notes=[f"只有 {len(months)} 期且不連續：{months}", "工廠家數 ≠ 職缺；只做現況描述，不做時間序列預測"])

    sv = _load("factory_survey")
    sv["metric"] = sv["item"].str.extract(r"-(.+?)\(單位")[0].map(
        {"工廠家數": "factories", "從業員工": "employees", "營業收入": "revenue_thousand_twd"})
    sv = sv.assign(year=sv["date"].str[:4].astype(int), industry=sv["field"])
    sv = sv.pivot_table(index=["year", "industry"], columns="metric", values="value", aggfunc="first").reset_index()
    write_processed(sv, "tc_factory_survey_city_annual",
                    sources=["臺中市政府經濟發展局 臺中市製造業工廠校正暨營運調查統計", "https://data.gov.tw/dataset/175730"],
                    grain="臺中市（全市）× 製造業中類 × 年",
                    notes=["全市層級，不是分區；分區請用 tc_factory_district_industry_annual（EE520）",
                           "工商普查年停辦，該年無資料"])
    return fc, sv


if __name__ == "__main__":
    fetch_all()
    transform()
