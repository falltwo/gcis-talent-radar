"""Distance from each Taichung district office to the nearest freeway or expressway interchange.

Writes ui/static/district-transport.json for the site scan's "靠近交通樞紐" criterion.
From OpenStreetMap (Overpass API), saved to data/raw/osm/district_transport.json; pass --refresh
to fetch again:
- interchanges: highway=motorway_junction (國道與快速公路交流道). System interchanges (系統交流道)
  only link freeways, rest areas (休息站、服務區) have no exit, and level crossings (平交路口) are
  not interchanges, so those are left out.
- the three hubs: 臺中港 (harbour), 臺中國際機場 (aerodrome RMQ) and 高鐵臺中站 (station run by 台灣高速鐵路);
  the Taiwan Railways station named 臺中港 is not the harbour, so the port is matched by its landuse=harbour tag.
- the district office (amenity=townhall, 區公所) as the district's reference point. Large districts
  such as 太平、和平、北屯 reach into the mountains, so their geometric centre is far from where
  business happens; the district office sits in the main settlement.

Data © OpenStreetMap contributors, ODbL.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

import requests

from etl.build_district_talent import districts_geometry, inside, km

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/osm/district_transport.json"
OUT = ROOT / "ui/static/district-transport.json"
OVERPASS = "https://overpass-api.de/api/interpreter"
# Taichung plus a margin, so interchanges just over the border (彰化、苗栗、南投) still count as nearest.
BBOX = ",".join(map(str, (23.95, 120.40, 24.50, 121.50)))
QUERIES = {
    "junctions": f'[out:json][timeout:90];node["highway"="motorway_junction"]({BBOX});out body;',
    "offices": f'[out:json][timeout:90];nwr["amenity"="townhall"]["name"~"區公所"]({BBOX});out center tags;',
    "hubs": f'[out:json][timeout:90];(nwr["landuse"~"^(harbour|port)$"]["name"~"^(臺中|台中)港$"]({BBOX});'
            f'nwr["aeroway"="aerodrome"]["iata"="RMQ"]({BBOX});'
            f'nwr["railway"="station"]["operator"~"高速鐵路"]["name"~"臺中|台中"]({BBOX}););out center tags;',
}
HUBS = {"port": "臺中港", "airport": "臺中國際機場", "hsr": "高鐵臺中站"}
NOT_AN_EXIT = ("系統", "休息站", "服務區", "平交路口")


def fetch(keys=None, data=None) -> dict:
    data = dict(data or {}, fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    for key, query in QUERIES.items():
        if keys and key not in keys:
            continue
        response = requests.post(OVERPASS, data={"data": query}, timeout=120,
                                 headers={"User-Agent": "gcis-talent-radar (research)"})
        response.raise_for_status()
        data[key] = response.json()["elements"]
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def junctions(elements: list) -> list[dict]:
    out = []
    for node in elements:
        name = (node.get("tags") or {}).get("name", "")
        if any(word in name for word in NOT_AN_EXIT):
            continue
        out.append({"name": name or None, "point": (node["lon"], node["lat"])})
    return out


def hubs(elements: list) -> dict:
    """港口、機場、高鐵站各一個點。"""
    out = {}
    for element in elements:
        tags = element.get("tags") or {}
        point = (element.get("lon") or element["center"]["lon"], element.get("lat") or element["center"]["lat"])
        key = ("port" if tags.get("landuse") in ("harbour", "port") else "airport" if tags.get("aeroway") == "aerodrome"
               else "hsr" if tags.get("railway") == "station" and "高速鐵路" in tags.get("operator", "") else None)
        if key and key not in out:
            out[key] = {"name": HUBS[key], "osm_name": tags.get("name"), "point": [round(point[0], 5), round(point[1], 5)]}
    missing = set(HUBS) - set(out)
    if missing:
        raise SystemExit(f"OpenStreetMap 找不到：{'、'.join(HUBS[k] for k in missing)}")
    return out


def offices(elements: list, shapes: dict) -> dict:
    """區公所 → 行政區；公所必須落在該區內，對不上就不用。"""
    out = {}
    for element in elements:
        name = (element.get("tags") or {}).get("name", "").replace("臺中市", "")
        point = (element.get("lon") or element["center"]["lon"], element.get("lat") or element["center"]["lat"])
        district = next((d for d in shapes if name.startswith(d)), None)
        if district and inside(point, shapes[district]["rings"]):
            out[district] = point
    return out


def build(data: dict) -> dict:
    shapes = districts_geometry()
    points = junctions(data["junctions"])
    office = offices(data["offices"], shapes)
    hub = hubs(data["hubs"])
    districts = {}
    for name, shape in shapes.items():
        origin = office.get(name, shape["label"])
        nearest = min(points, key=lambda j: km(origin, j["point"]))
        districts[name] = {
            "nearest_km": round(km(origin, nearest["point"]), 1),
            "nearest_name": nearest["name"],
            "inside": sum(1 for j in points if inside(j["point"], shape["rings"])),
            "from": "區公所" if name in office else "行政區中心",
            **{f"{key}_km": round(km(origin, tuple(h["point"])), 1) for key, h in hub.items()},
        }
    return {
        "source": "OpenStreetMap 國道與快速公路交流道（highway=motorway_junction，不含系統交流道、休息站、平交路口）、各區區公所位置",
        "source_url": "https://www.openstreetmap.org/copyright",
        "license": "© OpenStreetMap contributors, ODbL",
        "fetched_at": data.get("fetched_at"),
        "junctions": len(points),
        "hubs": hub,
        "rule": "區公所到最近交流道、臺中港、臺中國際機場、高鐵臺中站的直線距離（公里）；找不到區公所時用區內離邊界最遠的點",
        "districts": districts,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="重新向 Overpass API 抓交流道與區公所")
    args = ap.parse_args(argv)
    data = fetch() if args.refresh or not RAW.exists() else json.loads(RAW.read_text(encoding="utf-8"))
    if "hubs" not in data:  # 舊的原始檔還沒有港口、機場、高鐵，只補抓這一項
        data = fetch(keys={"hubs"}, data=data)
    result = build(data)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    near = sorted(result["districts"].items(), key=lambda kv: kv[1]["nearest_km"])
    fallback = [k for k, v in result["districts"].items() if v["from"] != "區公所"]
    print(f"{result['junctions']} 個交流道；沒對到區公所：{fallback or '無'}")
    print("最近：", [(k, v["nearest_km"], v["nearest_name"]) for k, v in near[:5]])
    print("最遠：", [(k, v["nearest_km"], v["nearest_name"]) for k, v in near[-5:]])


if __name__ == "__main__":
    main()
