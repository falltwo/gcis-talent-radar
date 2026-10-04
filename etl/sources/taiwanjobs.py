"""
E6：台灣就業通職缺快照（勞動部勞動力發展署，data.gov.tw/dataset/44062）
https://free.taiwanjobs.gov.tw/webservice_taipei/Webservice.ashx?city=13&zipno=428&count=1000&T=CSV

就業通只提供「當下」的職缺，沒有歷史 → 每天跑一次 fetch_snapshot() 才會累積出時間序列。
每次查詢上限 1,000 筆；某區碰到上限時會警告（目前最多的西屯區約 400 筆）。

處理
- 不保留 JOB_DETAIL（工作內容全文可能含聯絡人、電話）與職缺網址以外的聯絡資訊
- 工作地點不是臺中市該區（例如「台中市不限」）→ location_flag 標記，不刪
- 同一職缺可能出現在多個郵遞區號查詢 → 以 (snapshot_date, url) 去重
"""
import datetime as dt
import re

import pandas as pd

from etl.sources.common import RAW_DATA_DIR, TAICHUNG_ZIP, fetch, read_csv_bytes, session, write_processed

API = "https://free.taiwanjobs.gov.tw/webservice_taipei/Webservice.ashx?city=13&zipno={zip}&count=1000&T=CSV"
RAW = RAW_DATA_DIR / "taiwanjobs"
CAP = 1000
COLS = {
    "OCCU_DESC（職務名稱）": "job_title", "WK_TYPE（職務性質）": "work_type",
    "CJOB1_COUNT（職務大類別代碼）": "job_major_code", "CJOB_NAME1（職務大類別名稱）": "job_major",
    "CJOB2_COUNT（職務小類別代碼）": "job_minor_code", "CJOB_NAME2（職務小類別名稱）": "job_minor",
    "JOB_PERSON（雇用人數）": "openings", "STOP_DATE（應徵截止日期）": "stop_date", "CITYNAME（工作地點）": "work_location",
    "EXPERIENCE（工作經驗）": "experience", "WKTIME（工作時間）": "work_time", "SALARYCD（核薪方式）": "salary_basis",
    "NT_L（薪資範圍下限）": "salary_min", "NT_U（薪資範圍上限）": "salary_max", "EDGRDESC（最低學歷要求）": "min_education",
    "URL_QUERY（職缺資料URL）": "url", "COMPNAME（公司名稱）": "company", "TRANDATE（職缺更新日期）": "updated_date",
}


DROP_RAW = ["JOB_DETAIL（工作內容）"]   # 工作內容全文可能有聯絡人、電話，原始檔也不留


def strip_raw(path):
    d = read_csv_bytes(path.read_bytes(), dtype=str)
    d.drop(columns=[c for c in DROP_RAW if c in d.columns]).to_csv(path, index=False, encoding="utf-8-sig")
    return d


def fetch_snapshot(date: str = None):
    """manifest 記錄的是 API 原始回應的雜湊；落地的檔案已刪除工作內容欄"""
    date = date or dt.date.today().isoformat()
    s = session()
    for zipcode, district in TAICHUNG_ZIP.items():
        path = RAW / date / f"{zipcode}.csv"
        if path.exists():
            continue
        b = fetch(s, "taiwanjobs", API.format(zip=zipcode), path, min_bytes=10, delay=1.0)
        n = len(strip_raw(path)) if b.strip() else 0
        if n >= CAP:
            print(f"  ⚠ {district}（{zipcode}）達 {CAP} 筆上限，該區職缺可能不完整")
    return date


def transform():
    frames = []
    for snap in sorted(p for p in RAW.iterdir() if p.is_dir()):
        for f in sorted(snap.glob("*.csv")):
            b = f.read_bytes()
            if not b.strip():
                continue
            d = read_csv_bytes(b, dtype=str)
            d = d[[c for c in COLS if c in d.columns]].rename(columns=COLS)
            d.insert(0, "snapshot_date", snap.name)
            d.insert(1, "query_zip", f.stem)
            d.insert(2, "query_district", TAICHUNG_ZIP[f.stem])
            frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    before = len(df)
    df = df.drop_duplicates(["snapshot_date", "url"]).reset_index(drop=True)
    loc = df["work_location"].fillna("").str.replace("臺", "台")
    df["location_flag"] = [
        "" if l == "台中市" + d else "taichung_unspecified" if l in ("台中市不限", "台中市") else
        "other_district" if l.startswith("台中市") else "outside_taichung"
        for l, d in zip(loc, df["query_district"])]
    for c in ("openings", "salary_min", "salary_max"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    snaps = sorted(df.snapshot_date.unique())
    write_processed(df, "tc_taiwanjobs_snapshot",
                    sources=["勞動部勞動力發展署 台灣就業通職缺", "https://data.gov.tw/dataset/44062", API.format(zip="{郵遞區號}")],
                    grain="快照日 × 職缺（查詢郵遞區號 × 職類）",
                    notes=[f"快照日期：{snaps}（每天跑一次才會累積歷史）", f"跨區重複的職缺已去除 {before - len(df)} 筆",
                           "location_flag：taichung_unspecified＝工作地點寫台中市不限；other_district／outside_taichung＝與查詢區不符",
                           "不含工作內容全文（可能有聯絡資訊）", "只涵蓋在台灣就業通刊登的雇主，不是所有職缺"])
    return df


if __name__ == "__main__":
    fetch_snapshot()
    transform()
