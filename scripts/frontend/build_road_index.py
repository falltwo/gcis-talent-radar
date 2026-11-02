"""Build a partial road-name index from existing official GCIS address snapshots."""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
def chinese_number(match):
    number = int(match[0])
    digits = '零一二三四五六七八九'
    if number < 10:
        return digits[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        return (digits[tens] if tens > 1 else '') + '十' + (digits[ones] if ones else '')
    return match[0]

roads = {}
files = sorted((ROOT / 'data/raw/gcis_lists').glob('*/*2025*.csv')) + sorted((ROOT / 'data/raw/gcis_lists').glob('*/*2026*.csv'))
for file in files:
    with file.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            address = row.get('公司所在地', '')
            match = re.match(r'[臺台]中市([^區]+區)(.*)', address)
            if not match:
                continue
            district, rest = match.groups()
            rest = re.sub(r'\s+', '', rest)
            rest = re.sub(r'^[^路街道]{2,4}?[里村](?=.+(?:路|街|大道))', '', rest)
            rest = re.sub(r'^\d+鄰', '', rest)
            road = re.match(r'([\u4e00-\u9fff0-9]{1,16}?(?:大道|路|街)(?:[一二三四五六七八九十0-9]+段)?)', rest)
            if road:
                name = road[1]
                if re.search(r'[臺台]中[市縣]|鄰', name):
                    continue
                name = re.sub(r'[0-9]+(?=[段路街])', chinese_number, name)
                name = name.replace('台灣大道', '臺灣大道').replace('巿', '市')
                roads.setdefault(district, set()).add(name)
output = {'source': '經濟部 GCIS 公司登記異動公開資料（本地 2025–2026 快照）', 'coverage': '從登記地址擷取的道路名稱，非完整道路名冊；無道路或門牌座標。', 'districts': {k: sorted(v) for k, v in sorted(roads.items())}}
(ROOT / 'ui/static/road-index.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'{len(roads)} districts, {sum(map(len, roads.values()))} road names')
