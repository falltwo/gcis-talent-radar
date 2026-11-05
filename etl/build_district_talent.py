"""Per-district talent facts for the three-district report on the home page.

Writes ui/static/district-talent.json from local processed files only:
- university campuses inside or within RADIUS_KM of each district's boundary, with graduates
  of manufacturing-related departments (MOE department statistics, latest academic year).
  A school inside the district counts in full; outside, its weight falls linearly to zero at
  RADIUS_KM from the boundary, so neighbouring districts no longer get identical counts;
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


def districts_geometry():
    """Rings per district in a local km grid, plus a label point that always lies inside the district."""
    geo = json.loads((ROOT / "ui/static/taichung-districts.geojson").read_text(encoding="utf-8"))
    out = {}
    for feature in geo["features"]:
        rings = []
        def walk(coords):
            if isinstance(coords[0][0], (int, float)):
                rings.append([tuple(point[:2]) for point in coords])
            else:
                for item in coords:
                    walk(item)
        walk(feature["geometry"]["coordinates"])
        out[feature["properties"]["TOWNNAME"]] = {"rings": rings, "label": label_point(rings)}
    return out


def to_km(point):
    return (point[0] * 111.32 * math.cos(math.radians(24.15)), point[1] * 110.57)


def inside(point, rings):
    x, y = point
    hit = False
    for ring in rings:  # even-odd over every ring handles holes and multipolygons
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                hit = not hit
    return hit


def edge_km(point, rings):
    px, py = to_km(point)
    best = math.inf
    for ring in rings:
        for a, b in zip(ring, ring[1:] + ring[:1]):
            (ax, ay), (bx, by) = to_km(a), to_km(b)
            dx, dy = bx - ax, by - ay
            t = 0 if not dx and not dy else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
            best = min(best, math.hypot(px - ax - t * dx, py - ay - t * dy))
    return best


def label_point(rings, steps=40):
    # ponytail: grid search for the inside point farthest from the edge; polylabel if it ever needs to be exact.
    xs = [x for ring in rings for x, _ in ring]; ys = [y for ring in rings for _, y in ring]
    best, far = None, -1
    for i in range(steps + 1):
        for j in range(steps + 1):
            point = (min(xs) + (max(xs) - min(xs)) * i / steps, min(ys) + (max(ys) - min(ys)) * j / steps)
            if inside(point, rings):
                distance = edge_km(point, rings)
                if distance > far:
                    best, far = point, distance
    return [round(best[0], 5), round(best[1], 5)]


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
    for name, shape in districts_geometry().items():
        near = []
        for school in schools.values():
            if not school["graduates"]:
                continue
            distance = 0.0 if inside(school["point"], shape["rings"]) else edge_km(school["point"], shape["rings"])
            if distance <= RADIUS_KM:
                near.append({**school, "km": round(distance, 1), "weight": round(1 - distance / RADIUS_KM, 2)})
        near.sort(key=lambda school: (school["km"], -school["graduates"]))
        job = jobs.get(name, {"postings": 0, "openings": 0, "salaries": [], "ceilings": []})
        districts[name] = {
            "label_point": shape["label"],
            "graduates_nearby": round(sum(school["graduates"] * school["weight"] for school in near)),
            "graduates_in_district": sum(school["graduates"] for school in near if school["km"] == 0),
            "schools": [{key: school[key] for key in ("name", "district", "km", "weight", "graduates", "top_departments")} for school in near],
            "postings": job["postings"], "openings": job["openings"],
            "salary_floor_median": round(statistics.median(job["salaries"])) if job["salaries"] else None,
            "salary_samples": len(job["salaries"]),
            "salary_ceiling_median": round(statistics.median(job["ceilings"])) if job["ceilings"] else None,
            "salary_ceiling_samples": len(job["ceilings"]),
        }
    return {
        "academic_year": year, "radius_km": RADIUS_KM, "distance": "school to district boundary; 0 when inside", "jobs_snapshot": snapshot,
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
    taiping = data["districts"]["太平區"]
    assert taiping["schools"][0]["name"] == "國立勤益科技大學" and taiping["schools"][0]["km"] == 0, "勤益 sits inside 太平區"
    assert taiping["graduates_nearby"] != data["districts"]["大里區"]["graduates_nearby"], "neighbours should differ once weighted"
