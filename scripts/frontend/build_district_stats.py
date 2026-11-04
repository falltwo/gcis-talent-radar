"""Write the district statistics shown on the map's industry layer."""
import csv
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACTORIES = ROOT / "data" / "processed" / "tc_factory_district_industry_annual.csv"
DATABASE = ROOT / "database" / "mismatch_system.db"
TARGET = ROOT / "ui" / "static" / "district-stats.json"
MANUFACTURING_JOBS = ("技術／維修／操作", "品管／製造／環衛")


def factory_stats():
    with FACTORIES.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    year = max(int(row["year"]) for row in rows)
    districts = {}
    for row in rows:
        if int(row["year"]) != year:
            continue
        # A missing value stays null: the source published no number, which is not zero.
        count = int(float(row["factories"])) if row["factories"] else None
        districts.setdefault(row["district"], {})[row["industry"]] = count
    return {
        "year": year,
        "source": "經濟部工廠校正統計調查（EE520）",
        "source_url": "https://service.moea.gov.tw/EE520/investigate/InvestigateG.aspx",
        "districts": districts,
    }


def job_stats():
    connection = sqlite3.connect(DATABASE)
    snapshot = connection.execute("SELECT MAX(snapshot_date) FROM official_job_fetch_audit").fetchone()[0]
    audits = connection.execute(
        "SELECT district, limit_reached FROM official_job_fetch_audit WHERE snapshot_date = ?",
        (snapshot,),
    ).fetchall()
    placeholders = ",".join("?" for _ in MANUFACTURING_JOBS)
    groups = {
        "all": ("", ()),
        "manufacturing": (f"AND occupation_major_name IN ({placeholders})", MANUFACTURING_JOBS),
    }
    # Every audited district starts at zero, so a real empty result differs from a missing fetch.
    metrics = {}
    for name, (clause, values) in groups.items():
        rows = connection.execute(
            f"SELECT district, COUNT(*), SUM(openings) FROM official_job_vacancies "
            f"WHERE snapshot_date = ? {clause} GROUP BY district",
            (snapshot, *values),
        ).fetchall()
        found = {district: (postings, openings) for district, postings, openings in rows}
        metrics[f"{name}_postings"] = {district: found.get(district, (0, 0))[0] for district, _ in audits}
        metrics[f"{name}_openings"] = {district: found.get(district, (0, 0))[1] for district, _ in audits}
    connection.close()
    return {
        "snapshot_date": snapshot,
        "source": "台灣就業通職缺清單",
        "source_url": "https://data.gov.tw/dataset/44062",
        "capped": [district for district, limit_reached in audits if limit_reached],
        "metrics": metrics,
    }


def main():
    TARGET.write_text(
        json.dumps({"factories": factory_stats(), "jobs": job_stats()}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
