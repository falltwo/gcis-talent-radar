"""Count GCIS company setups and dissolutions per Taichung district for the last 12 months.

Writes ui/static/gcis-district-activity.json. Reads only the local monthly lists in
data/raw/gcis_lists/{setup,dissolved}/YYYY-MM.csv; addresses that do not start with a
Taichung district are counted as unparsed, never guessed.

Each district also gets its current company count from the tax registry (BGMOPEN1, organisation
type 公司), the denominator of the net entry rate (setups − dissolutions) ÷ companies used by
Census BDS, Eurostat and ONS business demography. Run `python -m etl.run_real_etl --only gcis_registry`
or `python -m etl.daily_refresh` first so data/raw/tax_registry/bgmopen1_industry.csv exists.
"""
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import TAICHUNG_DISTRICTS

LISTS = ROOT / "data/raw/gcis_lists"
OUT = ROOT / "ui/static/gcis-district-activity.json"
TAX = ROOT / "data/raw/tax_registry/bgmopen1_industry.csv"
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
            reader = csv.DictReader(handle)
            if '公司所在地' not in (reader.fieldnames or []):
                raise ValueError(f'{kind}/{month}: missing 公司所在地 column')
            for row in reader:
                total += 1
                match = DISTRICT.match((row.get("公司所在地") or "").replace("台中市", "臺中市").strip())
                if match and match.group(1) in TAICHUNG_DISTRICTS:
                    found[match.group(1)] += 1
                    if roads is not None:
                        rest = VILLAGE.sub("", (row.get("公司所在地") or "").replace("台中市", "臺中市").strip()[match.end():])
                        road = ROAD.match(rest)
                        if road:
                            roads.setdefault(match.group(1), Counter())[road.group(1)] += 1
                else:
                    unparsed += 1
    return found, total, unparsed


def companies() -> tuple[Counter, str]:
    """各區現有公司家數（稅籍組織別為公司、不含分公司，營業地址在該區）與稅籍檔日期。"""
    found = Counter()
    with open(TAX, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {'臺中行政區', '組織別名稱'}.issubset(reader.fieldnames or []):
            raise ValueError(f'{TAX}: missing tax stock columns')
        for row in reader:
            kind = row.get("組織別名稱") or ""
            # 清冊只算公司，分公司另外登記，不算進分母
            if row.get("臺中行政區") in TAICHUNG_DISTRICTS and "公司" in kind and "分公司" not in kind:
                found[row["臺中行政區"]] += 1
    if not found:
        raise ValueError(f"{TAX} 沒有可用的公司存量；請先重新下載稅籍檔")
    return found, datetime.fromtimestamp(TAX.stat().st_mtime).date().isoformat()


def build() -> dict:
    available = {path.stem for kind in ('setup','dissolved') for path in (LISTS/kind).glob('*.csv')
                 if re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])', path.stem)}
    if not available:
        raise ValueError('No GCIS monthly setup/dissolution lists')
    latest = max(available)
    window = months(latest, 12)
    roads: dict = {}
    setup, setup_total, setup_unparsed = count("setup", window, roads)
    dissolved, dissolved_total, dissolved_unparsed = count("dissolved", window)
    for kind,total,unparsed in [('setup',setup_total,setup_unparsed),('dissolved',dissolved_total,dissolved_unparsed)]:
        if total and unparsed/total >= .01:
            raise ValueError(f'{kind}: too many unparsed addresses ({unparsed}/{total})')
    stock, stock_date = companies()
    names = sorted(set(setup) | set(dissolved))
    return {
        "window": [window[0], window[-1]],
        "missing_months": [m for m in window if not (LISTS / "setup" / f"{m}.csv").exists() or not (LISTS / "dissolved" / f"{m}.csv").exists()],
        "source": "經濟部商工行政資料開放平台：公司設立登記、解散登記清冊（臺中市）",
        "source_url": "https://data.gcis.nat.gov.tw/",
        "companies_source": "財政部全國營業（稅籍）登記資料 BGMOPEN1：組織別為公司（不含分公司）、營業地址在該區",
        "companies_as_of": stock_date,
        "coverage": {
            "setup": {"rows": setup_total, "unparsed": setup_unparsed},
            "dissolved": {"rows": dissolved_total, "unparsed": dissolved_unparsed},
        },
        # The road with the most new registrations stands in for "where business happens" in a district.
        "districts": {name: {"setup": setup[name], "dissolved": dissolved[name], "companies": stock.get(name),
                             "top_road": roads[name].most_common(1)[0][0] if roads.get(name) else None} for name in names},
    }


if __name__ == "__main__":
    data = build()
    from etl.build_site_data import write_artifact
    write_artifact(OUT,data)
    print(data["window"], data["missing_months"], data["coverage"], len(data["districts"]), "districts")
