"""Validated local inputs for district map/report artifacts; never fetches data."""
import csv
import datetime as dt
import math
from pathlib import Path

from config import BASE_DIR
from etl.sources.common import TAICHUNG_ZIP

# Job-family proxies, not the employer's official industry classification.
MAP_JOB_FAMILIES = frozenset({'技術／維修／操作', '品管／製造／環衛'})
TALENT_JOB_FAMILIES = MAP_JOB_FAMILIES | {'工程／研發／生技'}


def csv_rows(path, required):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f'{Path(path).name}: empty CSV header')
        missing = set(required) - set(reader.fieldnames)
        if missing:
            raise ValueError(f'{Path(path).name}: missing columns {sorted(missing)}')
        return list(reader)


def nonnegative_number(value, label, integer=False):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Invalid {label}: {value!r}') from exc
    if not math.isfinite(number) or number < 0 or (integer and not number.is_integer()):
        raise ValueError(f'Invalid {label}: {value!r}')
    return int(number) if integer else number


def latest_jobs(processed_dir=None, raw_dir=None, query_limit=1000):
    processed_dir = Path(processed_dir or BASE_DIR/'data/processed')
    raw_dir = Path(raw_dir or BASE_DIR/'data/raw')
    rows = csv_rows(processed_dir/'tc_taiwanjobs_snapshot.csv',
                    ['snapshot_date','query_district','url','job_major','openings','work_location','location_flag'])
    snapshots = {row['snapshot_date'] for row in rows}
    if not snapshots:
        raise ValueError('Empty TaiwanJobs snapshot')
    for day in snapshots:
        if dt.date.fromisoformat(day).isoformat() != day:
            raise ValueError('Invalid TaiwanJobs snapshot date')
    snapshot = max(snapshots)
    rows = [row for row in rows if row['snapshot_date'] == snapshot]
    capped, missing, raw_counts = [], [], {}
    for zipcode, district in TAICHUNG_ZIP.items():
        path = raw_dir/'taiwanjobs'/snapshot/(zipcode+'.csv')
        if not path.is_file():
            missing.append(district)
            continue
        raw_counts[district] = len(csv_rows(path, ['OCCU_DESC（職務名稱）','CITYNAME（工作地點）','URL_QUERY（職缺資料URL）']))
        if raw_counts[district] >= query_limit:
            capped.append(district)
    identities = {}
    for row in rows:
        identities.setdefault(row['query_district'],set()).add(job_identity(row))
    for district, keys in identities.items():
        if district in raw_counts and len(keys) > raw_counts[district]:
            raise ValueError(f'{district}: processed rows exceed raw snapshot audit')
    seen, retained, excluded, duplicates = set(), [], 0, 0
    for row in rows:
        district = row['query_district']
        place = ''.join(row['work_location'].split()).replace('台', '臺')
        if district not in TAICHUNG_ZIP.values() or row['location_flag'] or not place.startswith('臺中市'+district):
            excluded += 1
            continue
        if district in missing:
            raise ValueError(f'{district}: processed observations have no raw snapshot audit')
        identity = job_identity(row)
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        row = dict(row)
        row['openings'] = nonnegative_number(row['openings'], 'openings', integer=True)
        retained.append(row)
    return {'rows':retained, 'snapshot_date':snapshot, 'capped':sorted(capped),
            'missing_districts':sorted(missing), 'raw_rows_by_district':raw_counts,
            'excluded_location_rows':excluded, 'duplicate_rows':duplicates, 'query_limit':query_limit}


def job_identity(row):
    return row['url'].strip() or '|'.join(row.get(k,'') for k in
        ('query_district','job_title','company','work_location','updated_date'))
