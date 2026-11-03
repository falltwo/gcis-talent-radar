"""Offline read access to the active, imported education snapshot."""
import json
import math
import os
import sqlite3
import unicodedata
from engine.campus_search import expand, suggestions
from engine.education_contacts import read_institution_contacts, missing_phone
from contextlib import contextmanager
from pathlib import Path
from config import BASE_DIR, TAICHUNG_DISTRICTS


class EducationDataUnavailable(RuntimeError):
    pass


def education_db_path():
    """The campus directory has its own database; never fall back to legacy marts."""
    path = Path(os.environ.get('EDUCATION_DB_PATH') or 'database/education_directory.sqlite3').expanduser()
    return path if path.is_absolute() else BASE_DIR / path


@contextmanager
def directory_connection(db_path=None):
    # mode=ro also prevents an accidentally wrong path creating a blank DB.
    try:
        conn = sqlite3.connect(Path(db_path or education_db_path()).resolve().as_uri() + '?mode=ro', uri=True)
    except sqlite3.OperationalError as exc:
        raise EducationDataUnavailable('科系資料庫目前無法讀取') from exc
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('BEGIN')
        yield conn
    except (sqlite3.DatabaseError, json.JSONDecodeError) as exc:
        raise EducationDataUnavailable('校園資料目前無法讀取，請稍後重試') from exc
    finally:
        conn.close()


def _release(conn, release_id=None):
    try:
        if release_id:
            row = conn.execute('SELECT * FROM education_releases WHERE release_id=?',(release_id,)).fetchone()
        else:
            row = conn.execute('''SELECT r.* FROM education_releases r
                JOIN education_active_release a ON a.release_id=r.release_id WHERE a.singleton=1''').fetchone()
    except sqlite3.OperationalError as exc:
        raise EducationDataUnavailable('科系資料尚未匯入') from exc
    if row is None:
        raise EducationDataUnavailable('尚無已發布的科系資料')
    return dict(row)


def get_education_coverage(db_path=None):
    with directory_connection(db_path) as conn:
        release = _release(conn)
        sources = [dict(r) for r in conn.execute('''SELECT source_key,url,fetched_at,sha256
            FROM education_sources WHERE release_id=? AND source_key IN ('schools','departments','students')
            ORDER BY source_key''', (release['release_id'],))]
        return {'release_id': release['release_id'], 'created_at': release['created_at'],
                **json.loads(release['summary_json']), 'sources': sources}


def _coordinate_references(conn, release_id):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='education_coordinate_evidence'").fetchone():
        return {}
    result = {}
    for r in conn.execute('''SELECT e.campus_id,e.source_feature_id,e.source_feature_name,e.source_feature_period,
            e.target_crs AS crs,e.point_type,e.method,e.verified_at,
            s.url AS source_url,v.url AS administrative_validation_url
            FROM education_coordinate_evidence e
            JOIN education_sources s ON s.release_id=e.release_id AND s.source_key=e.source_key
            JOIN education_sources v ON v.release_id=e.release_id AND v.source_key=e.validation_source_key
            WHERE e.release_id=?''',(release_id,)):
        row=dict(r)
        result[row.pop('campus_id')]=row
    return result


def list_education_institutions(db_path=None):
    with directory_connection(db_path) as conn:
        release = _release(conn)
        rid = release['release_id']
        contacts = read_institution_contacts(conn, rid)
        coordinates = _coordinate_references(conn,rid)
        rows = [dict(r) for r in conn.execute('''SELECT i.*,
            (SELECT COUNT(*) FROM education_departments d WHERE d.release_id=i.release_id AND d.institution_id=i.institution_id) AS department_count
            FROM education_institutions i WHERE i.release_id=? AND in_taichung_scope=1 ORDER BY institution_id''', (rid,))]
        for row in rows:
            row.pop('release_id')
            row['school_phone'] = contacts.get(row['institution_id'], missing_phone())
            row['campuses'] = [dict(c) for c in conn.execute('''SELECT c.campus_id,c.name,c.address,c.city,c.district,
                c.postal_code,c.latitude,c.longitude,c.address_status,c.coordinate_status,s.url AS source_url,s.fetched_at
                FROM education_campuses c JOIN education_sources s USING(release_id,source_key)
                WHERE c.release_id=? AND c.institution_id=? ORDER BY c.campus_id''', (rid, row['institution_id']))]
            for campus in row['campuses']:
                campus['coordinate_reference'] = coordinates.get(campus['campus_id'])
        return {'release_id': rid, 'academic_year': release['academic_year'], 'items': rows,
                'total': len(rows), 'scope': '臺中正式教學校區所屬學校；各校外縣市校區亦列出以免誤判位置'}


def search_education_departments(q='', institution_id=None, district=None, page=1, page_size=50, db_path=None, release_id=None):
    if not 1 <= page_size <= 100 or page < 1:
        raise ValueError('page 至少為 1，page_size 限 1–100')
    if len(q) > 80:
        raise ValueError('查詢文字限 80 字')
    if district is not None and district not in TAICHUNG_DISTRICTS:
        raise ValueError('請選擇有效的臺中行政區')
    with directory_connection(db_path) as conn:
        release = _release(conn, release_id)
        rid = release['release_id']
        coordinates = _coordinate_references(conn,rid)
        conditions, args = ['d.release_id=?'], [rid]
        if q:
            # Treat SQL LIKE metacharacters as text, never as caller wildcards.
            escaped = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            conditions.append("(d.name LIKE ? ESCAPE '\\' OR i.name LIKE ? ESCAPE '\\')")
            args.extend(['%'+escaped+'%']*2)
        if institution_id:
            conditions.append('d.institution_id=?')
            args.append(institution_id)
        if district:
            # Only direct, audited teaching evidence qualifies a department for
            # strict geographic search. Contact and single-campus inference are
            # exposed for inspection but cannot silently become verified data.
            conditions.append('''EXISTS (SELECT 1 FROM education_department_campuses r
                JOIN education_campuses c USING(release_id,campus_id)
                WHERE r.release_id=d.release_id AND r.department_id=d.department_id
                AND r.relation_type='VERIFIED_TEACHING' AND c.city='臺中市' AND c.district=?)''')
            args.append(district)
        base = '''FROM education_departments d JOIN education_institutions i
            USING(release_id,institution_id) WHERE ''' + ' AND '.join(conditions)
        total = conn.execute('SELECT COUNT(*) ' + base, args).fetchone()[0]
        rows = [dict(r) for r in conn.execute('''SELECT d.department_id,d.institution_id,i.name AS institution_name,
            d.department_code,d.name,d.college,d.website,d.registry_listed,s.url AS source_url
            FROM education_departments d JOIN education_institutions i USING(release_id,institution_id)
            JOIN education_sources s ON s.release_id=d.release_id AND s.source_key=d.source_key
            WHERE ''' + ' AND '.join(conditions) + ' ORDER BY d.institution_id,d.department_code LIMIT ? OFFSET ?',
            (*args, page_size, (page-1)*page_size))]
        for row in rows:
            row['campus_relations'] = [dict(c) for c in conn.execute('''SELECT c.campus_id,c.name,c.city,c.district,c.address,
                c.latitude,c.longitude,c.coordinate_status,
                r.relation_type,s.url AS source_url FROM education_department_campuses r
                JOIN education_campuses c USING(release_id,campus_id)
                JOIN education_sources s ON s.release_id=r.release_id AND s.source_key=r.source_key
                WHERE r.release_id=? AND r.department_id=? ORDER BY c.campus_id''', (rid, row['department_id']))]
            for campus in row['campus_relations']:
                campus['coordinate_reference'] = coordinates.get(campus['campus_id'])
        summary = json.loads(release['summary_json'])
        return {'release_id': rid, 'academic_year': release['academic_year'], 'total': total,
                'items': rows, 'page': page, 'page_size': page_size,
                'status': 'OK' if total else ('NO_VERIFIED_LOCATION' if district else 'NO_MATCH'),
                'limitations': summary['limitations'], 'search_type': 'DEPARTMENT_NAME_TEXT'}


def _search_text(value):
    return ''.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split()).replace('台', '臺').replace('巿', '市')


# Explicit name aliases only; this does not infer job relevance or campus location.
DEPARTMENT_NAME_ALIASES = {
    '資工': ('資訊工程',),
    '資工系': ('資訊工程',),
}


def _finite_number(value, name, lower=None, upper=None, positive=False):
    if isinstance(value, bool):
        raise ValueError(f'{name} 必須是有限數值')
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{name} 必須是有限數值') from exc
    if (not math.isfinite(number) or (lower is not None and number < lower)
            or (upper is not None and number > upper) or (positive and number <= 0)):
        raise ValueError(f'{name} 超出有效範圍')
    return number


def _distance_km(latitude, longitude, other_latitude, other_longitude):
    """Great-circle distance to a campus reference point, never commuting time."""
    lat1, lat2 = math.radians(latitude), math.radians(other_latitude)
    dlat, dlon = lat2 - lat1, math.radians(other_longitude - longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    h = min(1.0, max(0.0, h))
    return 6371.0088 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def search_education_campuses(latitude, longitude, radius_km=15, q='', db_path=None, include_related=False):
    """Find real Taichung campuses without inferring unverified teaching sites.

    A keyword can find an institution's unlocated departments, but those hits
    have their own field and explicit scope; they never become campus relations.
    All reads use one transaction so a published snapshot cannot change midway.
    """
    latitude = _finite_number(latitude, 'latitude', -90, 90)
    longitude = _finite_number(longitude, 'longitude', -180, 180)
    radius_km = _finite_number(radius_km, 'radius_km', positive=True)
    if not isinstance(q, str) or len(q) > 80:
        raise ValueError('查詢文字限 80 字')
    keyword = _search_text(q)
    expansion = expand(q)
    department_terms = expansion['direct']
    with directory_connection(db_path) as conn:
        release = _release(conn)
        rid = release['release_id']
        contacts = read_institution_contacts(conn, rid)
        summary = json.loads(release['summary_json'])
        coordinates = _coordinate_references(conn, rid)
        departments = [dict(row) for row in conn.execute('''
            SELECT d.department_id,d.institution_id,d.name,d.college,d.website,d.registry_listed,
                   s.url AS source_url
            FROM education_departments d JOIN education_sources s
            ON s.release_id=d.release_id AND s.source_key=d.source_key
            WHERE d.release_id=? ORDER BY d.department_code,d.name''', (rid,))]
        by_institution = {}
        for department in departments:
            by_institution.setdefault(department['institution_id'], []).append(department)
        by_id = {department['department_id']: department for department in departments}
        related_ids, campus_departments = set(), {}
        priorities = {'SINGLE_OFFICIAL_CAMPUS': 1, 'DEPARTMENT_CONTACT_ADDRESS': 2, 'VERIFIED_TEACHING': 3}
        labels = {'SINGLE_OFFICIAL_CAMPUS': '單一官方校區推定，非逐系教學校區核驗',
                  'DEPARTMENT_CONTACT_ADDRESS': '系所聯絡地址，非教學校區核驗',
                  'VERIFIED_TEACHING': '已核驗教學校區'}
        for relation in conn.execute('''
            SELECT r.campus_id,r.department_id,r.relation_type,s.url AS relation_source_url
            FROM education_department_campuses r JOIN education_sources s
            ON s.release_id=r.release_id AND s.source_key=r.source_key
            WHERE r.release_id=?''', (rid,)):
            department_id = relation['department_id']
            related_ids.add(department_id)
            if department_id not in by_id:
                continue
            related = campus_departments.setdefault(relation['campus_id'], {})
            existing = related.get(department_id)
            if existing and priorities.get(existing['relation_type'], 0) >= priorities.get(relation['relation_type'], 0):
                continue
            related[department_id] = {**by_id[department_id], 'relation_type': relation['relation_type'],
                                      'relation_label': labels.get(relation['relation_type'], '待核驗'),
                                      'relation_source_url': relation['relation_source_url']}
        campuses = conn.execute('''
            SELECT c.campus_id,c.institution_id,i.name AS institution_name,c.name,c.address,
                   c.city,c.district,c.latitude,c.longitude,c.coordinate_status,
                   s.url AS source_url,s.fetched_at,i.website,i.profile_url
            FROM education_campuses c JOIN education_institutions i USING(release_id,institution_id)
            JOIN education_sources s ON s.release_id=c.release_id AND s.source_key=c.source_key
            WHERE c.release_id=? AND c.city='臺中市' AND i.in_taichung_scope=1
            ORDER BY i.institution_id,c.campus_id''', (rid,)).fetchall()
        items, verified_count = [], 0
        for row in campuses:
            campus = dict(row)
            reference = coordinates.get(campus['campus_id'])
            # An arbitrary stored point does not qualify as verified geometry.
            if (campus['coordinate_status'] != 'VERIFIED_OFFICIAL_GEOMETRY' or not reference
                    or reference.get('crs') != 'EPSG:4326'
                    or campus['latitude'] is None or campus['longitude'] is None):
                continue
            try:
                lat = _finite_number(campus['latitude'], 'campus latitude', -90, 90)
                lon = _finite_number(campus['longitude'], 'campus longitude', -180, 180)
            except ValueError:
                continue
            verified_count += 1
            distance = _distance_km(latitude, longitude, lat, lon)
            if distance > radius_km:
                continue
            related = list(campus_departments.get(campus['campus_id'], {}).values())
            school_departments = by_institution.get(campus['institution_id'], [])
            unlocated = [department for department in school_departments if department['department_id'] not in related_ids]
            matched = [department for department in related
                       if any(term in _search_text(department['name']) for term in department_terms)]
            unlocated_matches = [department for department in unlocated
                                 if any(term in _search_text(department['name']) for term in department_terms)]
            related_matches = [dict(department, location_status='RELATED_TO_CAMPUS' if department['department_id'] in {d['department_id'] for d in related} else 'TEACHING_LOCATION_UNVERIFIED')
                               for department in related + unlocated
                               if include_related and keyword and any(term in _search_text(department['name']) for term in expansion['related'])
                               and not any(term in _search_text(department['name']) for term in department_terms)]
            tier = 'DIRECT'
            if not keyword:
                match_scope = 'ALL'
            elif keyword in _search_text(campus['institution_name']):
                match_scope = 'INSTITUTION_NAME'
            elif keyword in _search_text(campus['name']):
                match_scope = 'CAMPUS_NAME'
            elif matched:
                match_scope = 'CAMPUS_DEPARTMENT_NAME'
            elif unlocated_matches:
                match_scope = 'INSTITUTION_DEPARTMENT_UNLOCATED'
            elif related_matches:
                match_scope = 'RELATED_FIELD'
                tier = 'RELATED'
            else:
                continue
            items.append({**campus, 'latitude': lat, 'longitude': lon, 'distance_km': round(distance, 4),
                          'school_phone': contacts.get(campus['institution_id'], missing_phone()),
                          'coordinate_reference': reference, 'departments': related,
                          'institution_department_count': len(school_departments),
                          'unlocated_department_count': len(unlocated), 'matched_departments': matched,
                          'unlocated_department_matches': unlocated_matches, 'match_scope': match_scope,
                          'match_tier': tier, 'related_departments': related_matches,
                          'match_reason': ('相關領域：' + '、'.join(expansion['families'])) if tier == 'RELATED'
                                          else ('簡稱對應：' + '、'.join(department_terms) if expansion['alias'] else '名稱直接符合' if keyword else '搜尋範圍內的校區')})
        items.sort(key=lambda item: (item['match_tier'] != 'DIRECT', item['distance_km'], item['institution_name'], item['campus_id']))
        limitations = list(summary.get('limitations', []))
        for note in [
            '距離為選點至校園範圍內代表點的球面直線距離，不是校門距離或通勤距離。',
            '系所名稱檢索不等於職務相關性推薦；未核驗教學校區的系所不會當成已確認設於該校區。',
            '本查詢僅比對科系名稱與相關領域，不產生媒合分數。',
        ]:
            if note not in limitations:
                limitations.append(note)
        return {'release_id': rid, 'academic_year': release['academic_year'], 'created_at': release['created_at'],
                'source_as_of': release['source_as_of'], 'total': len(items), 'items': items,
                'query_expansion': {'input': q, 'department_terms': list(department_terms),
                                    'alias_applied': expansion['alias']},
                'search_rule_version': expansion['version'], 'include_related': include_related,
                'suggestions': suggestions(q, [d['name'] for d in departments]) if not items else [],
                'status': 'OK' if items else 'NO_MATCH', 'limitations': limitations,
                'search_type': 'CAMPUS_AND_DEPARTMENT_NAME_TEXT', 'distance_type': 'GREAT_CIRCLE',
                'origin': {'latitude': latitude, 'longitude': longitude}, 'radius_km': radius_km,
                'verified_campus_count': verified_count, 'coverage_campus_count': len(campuses)}
