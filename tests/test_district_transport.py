"""選址的交通便利：交流道只算能上下的，區公所要落在自己的行政區內。"""
from etl.build_district_transport import junctions, offices

SQUARE = [[(120.0, 24.0), (120.1, 24.0), (120.1, 24.1), (120.0, 24.1), (120.0, 24.0)]]


def node(name, lon=120.05, lat=24.05):
    return {"lon": lon, "lat": lat, "tags": {"highway": "motorway_junction", **({"name": name} if name else {})}}


def test_only_interchanges_you_can_exit_count():
    kept = junctions([node("太平交流道"), node("霧峰系統交流道"), node("清水服務區"), node("東草屯休息站"),
                      node("開礦村一號平交路口"), node(None)])
    assert [j["name"] for j in kept] == ["太平交流道", None]


def test_district_office_must_sit_inside_its_district():
    shapes = {"南區": {"rings": SQUARE}, "南屯區": {"rings": SQUARE}, "中區": {"rings": SQUARE}}
    found = offices([
        {"tags": {"name": "南區公所"}, "lon": 120.05, "lat": 24.05},
        {"tags": {"name": "臺中市南屯區公所"}, "center": {"lon": 120.06, "lat": 24.06}},
        {"tags": {"name": "中區區公所"}, "lon": 121.5, "lat": 25.0},  # 不在區內：不用
    ], shapes)
    assert set(found) == {"南區", "南屯區"}


def test_hubs_take_the_harbour_not_the_railway_station_named_after_it():
    from etl.build_district_transport import hubs

    found = hubs([
        {"lon": 120.6027, "lat": 24.3043, "tags": {"name": "臺中港", "railway": "station", "operator": "國營臺灣鐵路股份有限公司"}},
        {"center": {"lon": 120.5079, "lat": 24.2579}, "tags": {"name": "臺中港", "landuse": "harbour"}},
        {"center": {"lon": 120.6258, "lat": 24.2668}, "tags": {"name": "臺中清泉崗機場", "aeroway": "aerodrome", "iata": "RMQ"}},
        {"lon": 120.6159, "lat": 24.1121, "tags": {"name": "台中", "railway": "station", "operator": "台灣高速鐵路股份有限公司"}},
    ])
    assert found["port"]["point"] == [120.5079, 24.2579]
    assert found["airport"]["name"] == "臺中國際機場" and found["hsr"]["osm_name"] == "台中"
