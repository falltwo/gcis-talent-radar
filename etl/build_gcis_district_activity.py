"""Count GCIS company setups and dissolutions per Taichung district for the last 12 months.

Writes ui/static/gcis-district-activity.json. Reads only the local monthly lists in
data/raw/gcis_lists/{setup,dissolved}/YYYY-MM.csv; addresses that do not start with a
Taichung district are counted as unparsed, never guessed.
"""
import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LISTS = ROOT / "data/raw/gcis_lists"
OUT = ROOT / "ui/static/gcis-district-activity.json"
DISTRICT = re.compile(r"^臺中市([^市縣鄉鎮區]{1,4}區)")
# Same road rule as scripts/frontend/build_road_index.py, so the picked road is always in the sidebar menu.
ROAD = re.compile(r"([一-鿿0-9]{1,16}?(?:大道|路|街)(?:[一二三四五六七八九十0-9]+段)?)")
VILLAGE = re.compile(r"^[一-鿿]{1,4}[里村]")


def months(end: str, count: int) -> list[str]:
    year, month = map(int, end.split("-"))
    out = []
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return out[::-1]


def count(kind: str, window: list[str], roads: dict | None = None) -> tuple[Counter, int, int]:
    found, total, unparsed = Counter(), 0, 0
    for month in window:
        if not (LISTS / kind / f"{month}.csv").exists():
            continue
        with open(LISTS / kind / f"{month}.csv", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                total += 1
                match = DISTRICT.match((row.get("公司所在地") or "").replace("台中市", "臺中市").strip())
                if match:
                    found[match.group(1)] += 1
                    if roads is not None:
                        rest = VILLAGE.sub("", (row.get("公司所在地") or "").replace("台中市", "臺中市").strip()[match.end():])
                        road = ROAD.match(rest)
                        if road:
                            roads.setdefault(match.group(1), Counter())[road.group(1)] += 1
                else:
                    unparsed += 1
    return found, total, unparsed


def build() -> dict:
    latest = sorted(path.stem for path in (LISTS / "setup").glob("*.csv"))[-1]
    window = months(latest, 12)
    roads: dict = {}
    setup, setup_total, setup_unparsed = count("setup", window, roads)
    dissolved, dissolved_total, dissolved_unparsed = count("dissolved", window)
    names = sorted(set(setup) | set(dissolved))
    return {
        "window": [window[0], window[-1]],
        "missing_months": [m for m in window if not (LISTS / "setup" / f"{m}.csv").exists() or not (LISTS / "dissolved" / f"{m}.csv").exists()],
        "source": "經濟部商工行政資料開放平台：公司設立登記、解散登記清冊（臺中市）",
        "source_url": "https://data.gcis.nat.gov.tw/",
        "coverage": {
            "setup": {"rows": setup_total, "unparsed": setup_unparsed},
            "dissolved": {"rows": dissolved_total, "unparsed": dissolved_unparsed},
        },
        # The road with the most new registrations stands in for "where business happens" in a district.
        "districts": {name: {"setup": setup[name], "dissolved": dissolved[name],
                             "top_road": roads[name].most_common(1)[0][0] if roads.get(name) else None} for name in names},
    }


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(data["window"], data["missing_months"], data["coverage"], len(data["districts"]), "districts")
    assert data["coverage"]["setup"]["unparsed"] / data["coverage"]["setup"]["rows"] < 0.01, "too many unparsed addresses"
