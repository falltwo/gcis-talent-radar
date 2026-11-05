"""Per-district talent facts for the three-district report on the home page.

Writes ui/static/district-talent.json from local processed files only:
- university campuses within RADIUS_KM of each district's centre, with graduates of
  manufacturing-related departments (MOE department statistics, latest academic year);
- Taiwan Jobs postings in manufacturing-related job families: postings, requested
  workers and the median of the monthly salary floor employers posted.

There is no district-level data on job seekers or their expected pay; nothing here
estimates either.
"""
import csv
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data/processed"
OUT = ROOT / "ui/static/district-talent.json"
RADIUS_KM = 10
# ponytail: name rule for "manufacturing-related" departments; review with the team before quoting counts.
DEPT = re.compile(r"機械|機電|精密|自動化|模具|電機|工業工程|智慧製造|材料|車輛|動力|製造")
NOT_DEPT = re.compile(r"牙|醫|護|藥|食品")
JOB_FAMILIES = {"技術／維修／操作", "品管／製造／環衛", "工程／研發／生技"}


def rows(name):
    with open(PROCESSED / f"{name}.csv", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def centres():
    geo = json.loads((ROOT / "ui/static/taichung-districts.geojson").read_text(encoding="utf-8"))
    out = {}
    for feature in geo["features"]:
        points = []
        def walk(coords):
            if isinstance(coords[0], (int, float)):
                points.append(coords)
            else:
                for item in coords:
                    walk(item)
        walk(feature["geometry"]["coordinates"])
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        out[feature["properties"]["TOWNNAME"]] = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    return out


def km(a, b):
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * 111.32 * math.cos(lat), (a[1] - b[1]) * 110.57)


def build():
    depts = rows("tc_udb_dept_annual")
    # The newest year lists enrolment before graduates are published, so take the newest year that has graduates.
    year = max(row["academic_year"] for row in depts if row["graduates"])
    graduates = defaultdict(lambda: defaultdict(float))
    for row in depts:
        if row["academic_year"] == year and DEPT.search(row["dept"] or "") and not NOT_DEPT.search(row["dept"] or "") and row["graduates"]:
            graduates[row["school"]][row["dept"]] += float(row["graduates"])
    schools = {}
    for row in rows("education_campus_coordinates"):
        name = row["institution_name"]
        if name in schools:
            continue  # one point per school; departments are reported per school, not per campus
        by_dept = graduates.get(name, {})
        schools[name] = {
            "name": name, "district": row["district"],
            "point": (float(row["longitude"]), float(row["latitude"])),
            "graduates": round(sum(by_dept.values())),
            "top_departments": [d for d, _ in sorted(by_dept.items(), key=lambda item: -item[1])[:3]],
        }
    jobs = defaultdict(lambda: {"postings": 0, "openings": 0, "salaries": [], "ceilings": []})
    snapshot = None
    for row in rows("tc_taiwanjobs_snapshot"):
        snapshot = row["snapshot_date"]
        if row["job_major"] not in JOB_FAMILIES:
            continue
        item = jobs[row["query_district"]]
        item["postings"] += 1
        item["openings"] += int(float(row["openings"] or 0))
        if row["salary_basis"] == "月薪" and row["salary_min"]:
            item["salaries"].append(float(row["salary_min"]))
            if row["salary_max"]:
                item["ceilings"].append(float(row["salary_max"]))
    districts = {}
    for name, centre in centres().items():
        near = sorted(
            ({**school, "km": round(km(centre, school["point"]), 1)} for school in schools.values()
             if school["graduates"] and km(centre, school["point"]) <= RADIUS_KM),
            key=lambda school: school["km"])
        job = jobs.get(name, {"postings": 0, "openings": 0, "salaries": [], "ceilings": []})
        districts[name] = {
            "graduates_nearby": sum(school["graduates"] for school in near),
            "schools": [{key: school[key] for key in ("name", "district", "km", "graduates", "top_departments")} for school in near],
            "postings": job["postings"], "openings": job["openings"],
            "salary_floor_median": round(statistics.median(job["salaries"])) if job["salaries"] else None,
            "salary_samples": len(job["salaries"]),
            "salary_ceiling_median": round(statistics.median(job["ceilings"])) if job["ceilings"] else None,
            "salary_ceiling_samples": len(job["ceilings"]),
        }
    return {
        "academic_year": year, "radius_km": RADIUS_KM, "jobs_snapshot": snapshot,
        "department_rule": DEPT.pattern, "job_families": sorted(JOB_FAMILIES),
        "sources": {
            "graduates": "教育部大專校院各校科系別學生數（畢業生數）",
            "campuses": "教育部校區名冊座標（本專案整理，只含大專校院）",
            "jobs": "台灣就業通職缺清單 https://data.gov.tw/dataset/44062",
        },
        "districts": districts,
    }


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    sample = {k: data["districts"][k] for k in ("太平區", "大里區", "豐原區")}
    print(data["academic_year"], data["jobs_snapshot"])
    print(json.dumps(sample, ensure_ascii=False, indent=1))
    assert data["districts"]["太平區"]["schools"], "太平區 should have 勤益 within range"
