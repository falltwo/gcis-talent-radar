"""Fetch and load the three approved government datasets used by the tools.

Sources
-------
* TaiwanJobs vacancy list (dataset 44062): current observable vacancies.
* GCIS new company registrations by county/industry/month: monthly trend.
* Bureau of Labor Insurance statistics (dataset 100999): year-end baseline.

The loader intentionally fails closed.  Missing government data is never replaced
with synthetic rows, zeroes, interpolation, or the legacy 104-derived data.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import ssl
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BASE_DIR
from database.db_manager import db


TAIWANJOBS_DATASET_ID = "44062"
TAIWANJOBS_DATASET_URL = "https://data.gov.tw/dataset/44062"
TAIWANJOBS_API = "https://free.taiwanjobs.gov.tw/webservice_taipei/Webservice.ashx"
TAIWANJOBS_QUERY_LIMIT = 1000

GCIS_DATASET_ID = "01E5CFC6-9F09-4CB5-BE81-22B451E4B1BD"
GCIS_DATASET_URL = f"https://data.gcis.nat.gov.tw/od/detail?oid={GCIS_DATASET_ID}"
GCIS_LONG_CSV = BASE_DIR / "data" / "raw" / "gcis_new_by_industry_county" / "臺中市_monthly_long.csv"

LABOR_DATASET_ID = "100999"
LABOR_DATASET_URL = "https://data.gov.tw/dataset/100999"
DATA_GOV_METADATA = "https://data.gov.tw/api/v2/rest/dataset/{dataset_id}"

OFFICIAL_RAW = BASE_DIR / "data" / "raw" / "official"

TAICHUNG_POSTAL_CODES: Dict[str, str] = {
    "中區": "400", "東區": "401", "南區": "402", "西區": "403",
    "北區": "404", "北屯區": "406", "西屯區": "407", "南屯區": "408",
    "太平區": "411", "大里區": "412", "霧峰區": "413", "烏日區": "414",
    "豐原區": "420", "后里區": "421", "石岡區": "422", "東勢區": "423",
    "和平區": "424", "新社區": "426", "潭子區": "427", "大雅區": "428",
    "神岡區": "429", "大肚區": "432", "沙鹿區": "433", "龍井區": "434",
    "梧棲區": "435", "清水區": "436", "大甲區": "437", "外埔區": "438",
    "大安區": "439",
}


class GovernmentTLSAdapter(HTTPAdapter):
    """Keep certificate and hostname checks, disabling only Python 3.13 strict SKI."""

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)


def government_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", GovernmentTLSAdapter())
    session.headers.update({"User-Agent": "gcis-talent-radar/2.0 (government-open-data)"})
    return session


def _read_csv(content: bytes) -> pd.DataFrame:
    last_error = None
    for encoding in ("utf-8-sig", "cp950", "big5"):
        try:
            return pd.read_csv(io.BytesIO(content), encoding=encoding, dtype=str)
        except Exception as exc:  # pragma: no cover - exercised only for provider changes
            last_error = exc
    raise ValueError(f"政府 CSV 無法解碼：{last_error}")


def _column(df: pd.DataFrame, prefix: str) -> str:
    matches = [str(col) for col in df.columns if str(col).strip().startswith(prefix)]
    if not matches:
        raise ValueError(f"缺少必要欄位 {prefix}；實際欄位={list(df.columns)}")
    return matches[0]


def _integer(value, default: int = 0) -> int:
    parsed = pd.to_numeric(value, errors="coerce")
    return default if pd.isna(parsed) else int(parsed)


def _float(value):
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _normalise_place(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).replace("臺", "台")


def load_gcis_new_company_monthly(path: Path = GCIS_LONG_CSV) -> Dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"找不到 GCIS 真實月資料：{path}")

    frame = pd.read_csv(path, encoding="utf-8-sig")
    required = {"year_month", "county", "industry", "new_companies", "new_capital_million_twd"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"GCIS 彙整檔缺少欄位：{sorted(missing)}")

    loaded_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows: List[Tuple] = []
    for item in frame.to_dict("records"):
        year_month = str(item["year_month"])
        eligible = int(year_month >= "2012-06")
        rows.append((
            year_month,
            str(item["county"]),
            str(item["industry"]),
            _integer(item["new_companies"]),
            _float(item["new_capital_million_twd"]),
            eligible,
            GCIS_DATASET_ID,
            GCIS_DATASET_URL,
            loaded_at,
        ))

    db.init_db()
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM gcis_new_company_monthly")
        conn.executemany(
            """
            INSERT INTO gcis_new_company_monthly (
                year_month, county, industry, new_companies,
                new_capital_million_twd, is_model_eligible,
                source_dataset_id, source_url, loaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    available = sorted(set(frame.loc[frame["year_month"] >= "2012-06", "year_month"].astype(str)))
    periods = pd.period_range(available[0], available[-1], freq="M")
    gaps = [str(period) for period in periods if str(period) not in set(available)]
    return {
        "table": "gcis_new_company_monthly",
        "rows": len(rows),
        "months": int(frame["year_month"].nunique()),
        "period": [min(available), max(available)],
        "missing_months": gaps,
    }


def fetch_taiwanjobs(snapshot_date: str | None = None) -> Dict[str, object]:
    snapshot = snapshot_date or date.today().isoformat()
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    snapshot_dir = BASE_DIR / "data" / "processed" / "official" / "taiwanjobs"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    session = government_session()

    job_rows: Dict[str, Tuple] = {}
    audits: List[Tuple] = []
    failures: List[str] = []

    for district, postal_code in TAICHUNG_POSTAL_CODES.items():
        params = {
            "city": "13",
            "zipno": postal_code,
            "count": str(TAIWANJOBS_QUERY_LIMIT),
            "T": "CSV",
        }
        try:
            response = session.get(TAIWANJOBS_API, params=params, timeout=60)
            response.raise_for_status()
            if not response.content.startswith((b"\xef\xbb\xbf", b'"OCCU_DESC')):
                raise ValueError("回傳內容不是預期的 CSV")
            frame = _read_csv(response.content)
        except Exception as exc:
            failures.append(f"{district}({postal_code}): {exc}")
            continue

        columns = {
            key: _column(frame, prefix)
            for key, prefix in {
                "title": "OCCU_DESC",
                "major_code": "CJOB1_COUNT",
                "major_name": "CJOB_NAME1",
                "minor_code": "CJOB2_COUNT",
                "minor_name": "CJOB_NAME2",
                "openings": "JOB_PERSON",
                "deadline": "STOP_DATE",
                "location": "CITYNAME",
                "salary_type": "SALARYCD",
                "salary_lower": "NT_L",
                "salary_upper": "NT_U",
                "source_url": "URL_QUERY",
                "company": "COMPNAME",
                "updated_date": "TRANDATE",
            }.items()
        }

        retained = 0
        excluded = 0
        expected_place = _normalise_place(f"台中市{district}")
        for item in frame.to_dict("records"):
            location = str(item.get(columns["location"], "")).strip()
            if expected_place not in _normalise_place(location):
                excluded += 1
                continue

            source_url = str(item.get(columns["source_url"], "")).strip()
            fingerprint = source_url or "|".join([
                district,
                str(item.get(columns["company"], "")),
                str(item.get(columns["title"], "")),
                location,
                str(item.get(columns["updated_date"], "")),
            ])
            record_id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
            job_rows[record_id] = (
                snapshot,
                record_id,
                district,
                postal_code,
                str(item.get(columns["title"], "")).strip(),
                str(item.get(columns["major_code"], "")).strip(),
                str(item.get(columns["major_name"], "")).strip(),
                str(item.get(columns["minor_code"], "")).strip(),
                str(item.get(columns["minor_name"], "")).strip(),
                _integer(item.get(columns["openings"])),
                location,
                str(item.get(columns["salary_type"], "")).strip(),
                _float(item.get(columns["salary_lower"])),
                _float(item.get(columns["salary_upper"])),
                str(item.get(columns["company"], "")).strip(),
                str(item.get(columns["updated_date"], "")).strip(),
                str(item.get(columns["deadline"], "")).strip(),
                source_url,
                TAIWANJOBS_DATASET_ID,
                fetched_at,
            )
            retained += 1

        returned = len(frame)
        limit_reached = int(returned >= TAIWANJOBS_QUERY_LIMIT)
        audits.append((
            snapshot, district, postal_code, returned, retained, excluded,
            TAIWANJOBS_QUERY_LIMIT, limit_reached, fetched_at,
        ))

    if failures:
        raise RuntimeError("就業通部分行政區下載失敗，拒絕寫入不完整快照：" + "; ".join(failures))

    snapshot_columns = [
        "snapshot_date", "record_id", "district", "postal_code", "occupation_title",
        "occupation_major_code", "occupation_major_name", "occupation_minor_code",
        "occupation_minor_name", "openings", "work_location", "salary_type",
        "salary_lower", "salary_upper", "company_name", "updated_date",
        "application_deadline", "source_url", "source_dataset_id", "fetched_at",
    ]
    snapshot_file = snapshot_dir / f"taichung_{snapshot}.csv"
    pd.DataFrame(list(job_rows.values()), columns=snapshot_columns).to_csv(
        snapshot_file,
        index=False,
        encoding="utf-8-sig",
    )

    db.init_db()
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM official_job_vacancies WHERE snapshot_date = ?", (snapshot,))
        conn.execute("DELETE FROM official_job_fetch_audit WHERE snapshot_date = ?", (snapshot,))
        conn.executemany(
            """
            INSERT INTO official_job_vacancies (
                snapshot_date, record_id, district, postal_code, occupation_title,
                occupation_major_code, occupation_major_name, occupation_minor_code,
                occupation_minor_name, openings, work_location, salary_type,
                salary_lower, salary_upper, company_name, updated_date,
                application_deadline, source_url, source_dataset_id, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            list(job_rows.values()),
        )
        conn.executemany(
            """
            INSERT INTO official_job_fetch_audit (
                snapshot_date, district, postal_code, returned_count, retained_count,
                excluded_location_count, query_limit, limit_reached, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            audits,
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "table": "official_job_vacancies",
        "snapshot_date": snapshot,
        "districts": len(audits),
        "records": len(job_rows),
        "openings": sum(row[9] for row in job_rows.values()),
        "limit_reached_districts": [row[1] for row in audits if row[7]],
        "snapshot_file": str(snapshot_file),
        "privacy_note": "未保存 JOB_DETAIL、聯絡人、電話或電子郵件欄位",
    }


def _metadata_distributions(session: requests.Session, dataset_id: str) -> List[Dict[str, object]]:
    response = session.get(DATA_GOV_METADATA.format(dataset_id=dataset_id), timeout=60)
    response.raise_for_status()
    payload = json.loads(response.content.decode("utf-8"))
    return payload.get("result", {}).get("distribution", [])


def _distribution_url(item: Dict[str, object]) -> str:
    return str(
        item.get("resourceDownloadUrl")
        or item.get("downloadURL")
        or item.get("resourceAccessUrl")
        or item.get("accessURL")
        or ""
    )


def fetch_labor_insurance(years: Iterable[int] = range(107, 115)) -> Dict[str, object]:
    session = government_session()
    distributions = _metadata_distributions(session, LABOR_DATASET_ID)
    csv_items = [
        item for item in distributions
        if str(item.get("resourceFormat", "")).upper() == "CSV"
    ]

    code_item = next(
        (item for item in csv_items if "代號對照表" in str(item.get("resourceDescription", ""))),
        None,
    )
    if not code_item:
        raise RuntimeError("勞保資料集找不到 CSV 代號對照表")

    raw_dir = OFFICIAL_RAW / "labor_insurance"
    raw_dir.mkdir(parents=True, exist_ok=True)
    code_url = _distribution_url(code_item)
    code_response = session.get(code_url, timeout=60)
    code_response.raise_for_status()
    (raw_dir / "codebook.csv").write_bytes(code_response.content)
    codebook = _read_csv(code_response.content)
    codebook.columns = [str(col).strip() for col in codebook.columns]

    stat_col = _column(codebook, "統計項目")
    code_col = _column(codebook, "代號")
    name_col = _column(codebook, "對照中文名稱")
    code_names = {
        (str(row[stat_col]).strip(), str(row[code_col]).strip()): str(row[name_col]).strip()
        for row in codebook.to_dict("records")
    }

    wanted_years = [int(year) for year in years]
    rows: List[Tuple] = []
    loaded_at = datetime.now().astimezone().isoformat(timespec="seconds")
    used_urls: Dict[int, str] = {}

    for year in wanted_years:
        pattern = re.compile(rf"^{year}年統計資料$")
        item = next(
            (entry for entry in csv_items if pattern.match(str(entry.get("resourceDescription", "")).strip())),
            None,
        )
        if not item:
            raise RuntimeError(f"勞保資料集找不到 {year} 年 CSV")
        source_url = _distribution_url(item)
        response = session.get(source_url, timeout=60)
        response.raise_for_status()
        (raw_dir / f"{year}.csv").write_bytes(response.content)
        frame = _read_csv(response.content)
        frame.columns = [str(col).strip() for col in frame.columns]

        region_col = _column(frame, "地區別")
        unit_col = _column(frame, "單位類別")
        industry_col = _column(frame, "業別")
        employment_col = _column(frame, "單位就保註記")
        period_col = _column(frame, "資料年月")
        units_col = _column(frame, "本月底單位數")
        people_col = _column(frame, "本月底投保人數")
        salary_col = _column(frame, "平均投保薪資")

        taichung = frame[frame[region_col].astype(str).str.strip() == "66"]
        for row in taichung.to_dict("records"):
            region_code = str(row[region_col]).strip()
            unit_code = str(row[unit_col]).strip()
            industry_code = str(row[industry_col]).strip()
            employment_code = str(row[employment_col]).strip()
            rows.append((
                str(row[period_col]).strip(),
                region_code,
                code_names.get(("地區別", region_code), "臺中市"),
                unit_code,
                code_names.get(("單位類別", unit_code), unit_code),
                industry_code,
                code_names.get(("業別", industry_code), industry_code),
                employment_code,
                code_names.get(("單位就保註記", employment_code), employment_code),
                _integer(row[units_col]),
                _integer(row[people_col]),
                _float(row[salary_col]) or 0.0,
                LABOR_DATASET_ID,
                source_url,
                loaded_at,
            ))
        used_urls[year] = source_url

    snapshot_dir = BASE_DIR / "data" / "processed" / "official" / "labor_insurance"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file = snapshot_dir / "taichung_107_114.csv"
    snapshot_columns = [
        "data_period",
        "region_code",
        "region_name",
        "unit_type_code",
        "unit_type_name",
        "industry_code",
        "industry_name",
        "employment_insurance_code",
        "employment_insurance_name",
        "insured_units",
        "insured_people",
        "average_insured_salary",
        "source_dataset_id",
        "source_url",
        "loaded_at",
    ]
    pd.DataFrame(rows, columns=snapshot_columns).to_csv(
        snapshot_file,
        index=False,
        encoding="utf-8-sig",
    )

    db.init_db()
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM labor_insurance_baseline WHERE region_code = '66'")
        conn.executemany(
            """
            INSERT INTO labor_insurance_baseline (
                data_period, region_code, region_name, unit_type_code, unit_type_name,
                industry_code, industry_name, employment_insurance_code,
                employment_insurance_name, insured_units, insured_people,
                average_insured_salary, source_dataset_id, source_url, loaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "table": "labor_insurance_baseline",
        "years": wanted_years,
        "rows": len(rows),
        "region": "臺中市",
        "raw_directory": str(raw_dir),
        "snapshot_file": str(snapshot_file),
        "source_urls": used_urls,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load approved official labor-market datasets")
    parser.add_argument(
        "--only",
        choices=("all", "gcis", "jobs", "labor"),
        default="all",
        help="Dataset to load (default: all)",
    )
    args = parser.parse_args()

    results = []
    if args.only in ("all", "gcis"):
        results.append(load_gcis_new_company_monthly())
    if args.only in ("all", "jobs"):
        results.append(fetch_taiwanjobs())
    if args.only in ("all", "labor"):
        results.append(fetch_labor_insurance())
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
