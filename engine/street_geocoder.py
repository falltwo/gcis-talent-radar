"""User-triggered, cached road lookup using Photon / OpenStreetMap.

This demo adapter makes at most one upstream call per second in the single
server process. It is not an autocomplete endpoint or a bulk geocoder.
"""
import hashlib
import json
import math
import os
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.Lock()
_LAST_REQUEST = 0.0
CACHE_DIR = ROOT / 'data/cache/radar-geocoding'


class StreetLookupError(Exception):
    pass


def _normal(value):
    return str(value or '').replace('台', '臺').strip()


def select_road(features, district, road):
    """Never accept a fuzzy match in another district or a different street."""
    for feature in features:
        props = feature.get('properties', {})
        point = feature.get('geometry', {})
        if (props.get('countrycode') != 'TW'
                or _normal(props.get('city')) != '臺中市'
                or _normal(props.get('district')) != _normal(district)
                or _normal(props.get('name')) != _normal(road)
                or props.get('osm_key') != 'highway'
                or point.get('type') != 'Point'):
            continue
        coordinates = point.get('coordinates', [])
        if len(coordinates) != 2 or not all(isinstance(n, (int, float)) and math.isfinite(n) for n in coordinates):
            continue
        lon, lat = coordinates
        if not (120.4 < lon < 121.5 and 23.9 < lat < 24.6):
            continue
        return {
            'district': district, 'road': road, 'coordinates': coordinates,
            'precision': 'road_segment',
            'label': f'臺中市{district}{road}',
            'source': 'Photon / OpenStreetMap',
            'source_url': f"https://www.openstreetmap.org/way/{props.get('osm_id')}",
            'limitation': '定位在查得的其中一段道路，並非門牌或整條道路中心。',
        }
    return None


def locate_road(district, road):
    global _LAST_REQUEST
    index = json.loads((ROOT / 'ui/static/road-index.json').read_text(encoding='utf-8'))['districts']
    if road not in index.get(district, []):
        raise ValueError('請從此行政區的道路選單選擇地點。')
    endpoint = os.getenv('RADAR_GEOCODER_URL', 'https://photon.komoot.io/api/')
    key = hashlib.sha256(f'{endpoint}|{district}|{road}'.encode()).hexdigest()
    cache_file = CACHE_DIR / f'{key}.json'
    with _LOCK:
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime < 30 * 86400:
            try:
                return json.loads(cache_file.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                pass
        time.sleep(max(0, 1.1 - (time.monotonic() - _LAST_REQUEST)))
        _LAST_REQUEST = time.monotonic()
        try:
            response = requests.get(endpoint, params={
                'q': f'{road} {district}', 'limit': 12,
                'lat': 24.18, 'lon': 120.64,
            }, headers={'User-Agent': 'TaichungTalentRadar/1.0 (local research demo)'}, timeout=12)
            response.raise_for_status()
            payload = response.json()
            result = select_road(payload.get('features', []), district, road)
        except (requests.RequestException, ValueError, AttributeError, TypeError) as exc:
            raise StreetLookupError('道路定位服務暫時無法使用，請稍後再試。') from exc
        if result is None:
            result = {'district': district, 'road': road, 'coordinates': None,
                      'precision': 'unavailable', 'reason': '未找到相符行政區與道路的座標，沒有以其他地點代替。'}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temp = cache_file.with_suffix('.tmp')
        temp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        temp.replace(cache_file)
        return result
