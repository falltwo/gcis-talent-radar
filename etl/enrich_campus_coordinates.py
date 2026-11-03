"""Publish verified campus interior reference points as a new education snapshot.

Official NLSC school polygons are matched explicitly to MOE campuses. Compute an
interior point in the source projected CRS, transform to WGS84, then verify its
district with the public NLSC household-administration API. No geocoder guess or
handwritten numeric coordinate is accepted. Old snapshots remain unchanged.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import BASE_DIR
from engine.education_directory import education_db_path
DB_PATH = education_db_path()
from etl.load_education_directory import digest, now, norm, TZ, _source
from etl.load_official_labor_market import government_session

VERSION = 'campus-coordinates/1.0'
SELECTION = BASE_DIR/'data/processed/education_campus_coordinate_selection.json'
COORD_ROOT = BASE_DIR/'data/raw/education/coordinates'
COPY_TABLES = ['education_sources', 'education_institutions', 'education_campuses',
               'education_departments',
               'education_department_campuses', 'education_review_tasks']


def geo_modules():
    # Optional task-local installation; web/API serving never imports this stack.
    try:
        import shapefile
        from pyproj import CRS, Transformer
        from shapely.geometry import shape, Point
    except ImportError:
        local = BASE_DIR/'tmp/education-geo-deps'
        if not local.exists():
            raise RuntimeError('Install requirements-education-geospatial.txt to rebuild coordinates')
        sys.path.insert(0, str(local))
        import shapefile
        from pyproj import CRS, Transformer
        from shapely.geometry import shape, Point
    return shapefile, CRS, Transformer, shape, Point


def active_snapshot(db_path):
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT r.* FROM education_releases r JOIN education_active_release a USING(release_id) WHERE singleton=1').fetchone()
        if not row:
            raise ValueError('No education directory snapshot')
        campuses = [dict(r) for r in conn.execute('''SELECT c.*,i.name AS institution_name
            FROM education_campuses c JOIN education_institutions i USING(release_id,institution_id)
            WHERE c.release_id=? AND c.city='臺中市' ORDER BY campus_id''', (row['release_id'],))]
        return dict(row), campuses


def derive_points(zip_bytes, selection, campuses):
    shapefile, CRS, Transformer, shape, Point = geo_modules()
    choices = selection['matches']
    if len({r['campus_id'] for r in choices}) != len(choices):
        raise ValueError('Duplicate campus in coordinate selection')
    if len({r['object_id'] for r in choices}) != len(choices):
        raise ValueError('A polygon was assigned to multiple campuses')
    if {c['campus_id'] for c in campuses} != {c['campus_id'] for c in choices}:
        raise ValueError('Coordinate selection must cover every current Taichung campus exactly once')
    with ZipFile(io.BytesIO(zip_bytes)) as z:
        def member(suffix):
            paths = [p for p in z.namelist() if Path(p).suffix.lower() == suffix]
            if len(paths) != 1:
                raise ValueError('Expected a single shapefile '+suffix)
            return z.read(paths[0])
        wkt = member('.prj').decode('utf-8-sig')
        crs = CRS.from_wkt(wkt)
        # This release explicitly uses TWD97, central meridian 121, metres.
        if crs.to_epsg() != 3826:
            raise ValueError(f'Unexpected source CRS: {crs.to_string()}')
        encoding = member('.cpg').decode('ascii').strip()
        reader = shapefile.Reader(shp=io.BytesIO(member('.shp')), shx=io.BytesIO(member('.shx')),
                                  dbf=io.BytesIO(member('.dbf')), encoding=encoding)
        by_id = {}
        for r in reader.iterShapeRecords():
            props = r.record.as_dict()
            oid = int(props['OBJECTID'])
            if oid in by_id:
                raise ValueError('Duplicate polygon OBJECTID')
            by_id[oid] = (props, r.shape.__geo_interface__)
    forward = Transformer.from_crs(crs, 4326, always_xy=True)
    reverse = Transformer.from_crs(4326, crs, always_xy=True)
    by_campus = {c['campus_id']: c for c in campuses}
    points = []
    for choice in choices:
        campus = by_campus[choice['campus_id']]
        if choice['object_id'] not in by_id:
            raise ValueError('Selected polygon no longer exists')
        props, geometry = by_id[choice['object_id']]
        name = props['BLOCKNAME']
        if norm(name) != norm(choice['feature_name']) or int(props['BLOCKTYPE']) != 1:
            raise ValueError('Selected school feature changed identity')
        if norm(campus['institution_name']) not in norm(name):
            raise ValueError('School name does not match selected polygon')
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid or polygon.geom_type not in ('Polygon','MultiPolygon'):
            raise ValueError('Invalid school polygon')
        projected = polygon.representative_point()
        lon, lat = forward.transform(projected.x, projected.y)
        lon, lat = round(lon, 8), round(lat, 8)
        if not (math.isfinite(lon) and math.isfinite(lat) and 120.4 < lon < 121.6 and 24.0 < lat < 24.6):
            raise ValueError('Coordinate outside Taichung bounds or swapped axes')
        x, y = reverse.transform(lon, lat)
        if not polygon.covers(Point(x,y)) or math.hypot(x-projected.x,y-projected.y) > 0.02:
            raise ValueError('Coordinate transform/rounding does not preserve interior position')
        points.append({'campus_id':campus['campus_id'], 'institution_name':campus['institution_name'],
            'campus_name':campus['name'], 'address':campus['address'], 'district':campus['district'],
            'latitude':lat, 'longitude':lon, 'projected_x':projected.x, 'projected_y':projected.y,
            'source_feature_id':props['OBJECTID'], 'source_feature_name':name,
            'source_feature_period':props['YYYYMM'], 'source_crs':'EPSG:3826', 'target_crs':'EPSG:4326',
            'source_wkt':wkt, 'method':'SHAPELY_REPRESENTATIVE_POINT_THEN_PYPROJ_ALWAYS_XY',
            'point_type':'CAMPUS_INTERIOR_REFERENCE', 'match_note':choice['note'],
            'polygon_area_square_metres':polygon.area,
            'boundary_source_key':'coordinates-nlsc-school-polygons',
            'validation_source_key':'coordinates-district-'+str(props['OBJECTID'])})
    return points


def parse_district(xml_bytes):
    root = ElementTree.fromstring(xml_bytes)
    city, town = root.findtext('ctyName'), root.findtext('townName')
    if not city or not town:
        raise ValueError('Administrative API returned no city or district')
    return {'city':city, 'district':town, 'city_code':root.findtext('ctyCode'),
            'district_code':root.findtext('townCode'), 'village':root.findtext('villageName')}


def validate_district(point, content):
    result = parse_district(content)
    if norm(result['city']) != '臺中市' or result['district'] != point['district']:
        raise ValueError(f"Administrative mismatch: {point['campus_id']}: {result}")
    return result


def prepare_bundle(db_path=DB_PATH):
    parent, campuses = active_snapshot(db_path)
    selection_bytes = SELECTION.read_bytes()
    selection = json.loads(selection_bytes)
    folder = COORD_ROOT/datetime.now(TZ).strftime('%Y%m%dT%H%M%S%f')
    folder.mkdir(parents=True)
    session = government_session()
    response = session.get(selection['source_url'], timeout=90)
    response.raise_for_status()
    sources = [_source(folder, 'coordinates-nlsc-school-polygons', response.url, response.content, '.zip')]
    sources.append(_source(folder, 'coordinates-selection', 'urn:taichung-talent-radar:campus-coordinate-selection:1.0', selection_bytes, '.json'))
    points = derive_points(response.content, selection, campuses)
    for point in points:
        url = f"https://api.nlsc.gov.tw/other/TownVillagePointQuery1/{point['longitude']:.8f}/{point['latitude']:.8f}/4326"
        response = session.get(url,timeout=40)
        response.raise_for_status()
        district = validate_district(point,response.content)
        source = _source(folder, point['validation_source_key'], response.url, response.content, '.xml')
        sources.append(source)
        point['administrative_validation'] = district
        point['verified_at'] = source['fetched_at']
        print(f"Verified {point['institution_name']} / {point['campus_name']}: {point['latitude']}, {point['longitude']}",flush=True)
    manifest = {'version':VERSION,'parent_release_id':parent['release_id'], 'created_at':now(),
                'selection_version':selection['version'], 'sources':sources,'points':points}
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return folder


def checked_bundle(folder, campuses):
    folder = Path(folder).resolve()
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    contents = {}
    for source in manifest['sources']:
        file = (BASE_DIR/source['raw_path']).resolve()
        if not file.is_relative_to(COORD_ROOT.resolve()):
            raise ValueError('Coordinate source outside raw coordinate directory')
        content = file.read_bytes()
        if digest(content) != source['sha256']:
            raise ValueError('Coordinate source checksum mismatch')
        if source['source_key'] in contents:
            raise ValueError('Duplicate coordinate source key')
        contents[source['source_key']] = content
    points = derive_points(contents['coordinates-nlsc-school-polygons'],json.loads(contents['coordinates-selection']),campuses)
    saved = {p['campus_id']:p for p in manifest['points']}
    if len(saved) != len(manifest['points']) or set(saved) != {p['campus_id'] for p in points}:
        raise ValueError('Coordinate manifest point coverage mismatch')
    sources = {s['source_key']:s for s in manifest['sources']}
    for point in points:
        previous = saved[point['campus_id']]
        for key,value in point.items():
            if previous[key] != value:
                raise ValueError('Coordinate manifest differs from recomputed official geometry: '+key)
        source = sources[point['validation_source_key']]
        expected_suffix = f"/{point['longitude']:.8f}/{point['latitude']:.8f}/4326"
        if not source['url'].startswith('https://api.nlsc.gov.tw/other/TownVillagePointQuery1/') or not source['url'].endswith(expected_suffix):
            raise ValueError('District evidence refers to different coordinates')
        point['administrative_validation'] = validate_district(point,contents[point['validation_source_key']])
        point['verified_at'] = source['fetched_at']
    return manifest,points


def import_coordinates(folder,db_path=DB_PATH):
    parent,campuses = active_snapshot(db_path)
    manifest,points = checked_bundle(folder,campuses)
    signature = json.dumps({'version':VERSION, 'parent':manifest['parent_release_id'],
        'sources':sorted((s['source_key'],s['sha256']) for s in manifest['sources'])},sort_keys=True).encode()
    release_id = 'edu-geo-'+digest(signature)[:24]
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        existing=conn.execute('SELECT summary_json FROM education_releases WHERE release_id=?',(release_id,)).fetchone()
        if existing:
            return {'release_id':release_id,'already_imported':True,**json.loads(existing[0])}
        if parent['release_id'] != manifest['parent_release_id']:
            raise ValueError('Active snapshot changed; rebuild/review against current campuses')
        backup_path = None
        if Path(db_path).resolve() == DB_PATH.resolve():
            backup_dir=BASE_DIR/'data/backups/education'
            backup_dir.mkdir(parents=True,exist_ok=True)
            backup_path=backup_dir/('before-coordinates-'+datetime.now(TZ).strftime('%Y%m%dT%H%M%S%f')+'.db')
            with closing(sqlite3.connect(str(backup_path))) as backup:
                conn.backup(backup)
        conn.executescript((BASE_DIR/'database/education_schema.sql').read_text(encoding='utf-8'))
        summary=json.loads(parent['summary_json'])
        summary.update(verified_coordinates=len(points),pending_coordinates=0,campus_coordinate_status='COMPLETE',
                       coordinate_point_type='CAMPUS_INTERIOR_REFERENCE',coordinate_parent_release_id=parent['release_id'])
        summary['limitations'] = list(summary['limitations']) + ['座標為官方校園範圍內代表點，非校門或道路交通起點；直線距離不等於通勤距離。']
        with conn:
            # Check again under the publishing write lock; never overwrite a new
            # concurrently published active snapshot with stale enrichment.
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT release_id FROM education_active_release WHERE singleton=1').fetchone()[0] != parent['release_id']:
                raise ValueError('Active snapshot changed before publish')
            conn.execute('INSERT INTO education_releases VALUES (?,?,?,?,?,?)',
                (release_id,parent['academic_year'],VERSION,now(),parent['source_as_of'],json.dumps(summary,ensure_ascii=False)))
            for table in COPY_TABLES:
                columns=[r['name'] for r in conn.execute('PRAGMA table_info('+table+')') if r['name']!='release_id']
                names=','.join(columns)
                conn.execute(f'INSERT INTO {table} (release_id,{names}) SELECT ?,{names} FROM {table} WHERE release_id=?',
                             (release_id,parent['release_id']))
            conn.executemany('INSERT INTO education_sources VALUES (?,?,?,?,?,?)',[
                (release_id,s['source_key'],s['url'],s['fetched_at'],s['sha256'],s['raw_path']) for s in manifest['sources']])
            for p in points:
                cursor=conn.execute('''UPDATE education_campuses SET latitude=?,longitude=?,coordinate_status='VERIFIED_OFFICIAL_GEOMETRY'
                    WHERE release_id=? AND campus_id=? AND city='臺中市' ''',(p['latitude'],p['longitude'],release_id,p['campus_id']))
                if cursor.rowcount != 1:
                    raise ValueError('Expected exactly one campus coordinate update')
                conn.execute('''INSERT INTO education_coordinate_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (release_id,p['campus_id'],p['boundary_source_key'],p['validation_source_key'],p['source_feature_id'],
                     p['source_feature_name'],p['source_feature_period'],p['source_crs'],p['target_crs'],p['method'],
                     p['point_type'],p['projected_x'],p['projected_y'],p['verified_at'],json.dumps(p,ensure_ascii=False)))
                conn.execute("DELETE FROM education_review_tasks WHERE release_id=? AND entity_id=? AND task_type='COORDINATES'",(release_id,p['campus_id']))
            if conn.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Coordinate publication foreign key check failed')
            count=conn.execute("SELECT COUNT(*) FROM education_campuses WHERE release_id=? AND city='臺中市' AND latitude IS NOT NULL AND longitude IS NOT NULL",(release_id,)).fetchone()[0]
            if count!=len(campuses):
                raise ValueError('Incomplete coordinate publication')
            conn.execute('UPDATE education_active_release SET release_id=? WHERE singleton=1',(release_id,))
    return {'release_id':release_id,'already_imported':False,'parent_release_id':parent['release_id'],
            'backup_path':str(backup_path) if backup_path else None,**summary}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline',type=Path)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--db',type=Path,default=DB_PATH)
    args=parser.parse_args()
    folder=args.offline or prepare_bundle(args.db)
    if args.prepare_only:
        print('Prepared coordinate bundle:',folder)
        return
    result=import_coordinates(folder,args.db)
    result['manifest_path']=str(Path(folder).resolve()/'manifest.json')
    result['database_path']=str(args.db.resolve())
    report=BASE_DIR/'reports/education_coordinate_import.json'
    if result['already_imported'] and report.exists():
        previous=json.loads(report.read_text(encoding='utf-8'))
        if previous.get('release_id')==result['release_id'] and previous.get('database_path')==result['database_path']:
            result['backup_path']=previous.get('backup_path')
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
