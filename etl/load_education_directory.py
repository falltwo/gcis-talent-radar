"""Download the complete MOE roster, departments and campus addresses into SQLite.

No invented coordinates or automatic headquarters substitution. Official campus
addresses, single-campus inference and verified teaching locations are distinct.
The loader never writes the legacy department/UCAN/forecast marts.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import sys
import unicodedata
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup
from config import BASE_DIR, TAICHUNG_DISTRICTS
from engine.education_directory import education_db_path
DB_PATH = education_db_path()
from etl.load_official_labor_market import government_session

VERSION = 'education-directory/2.0'
TZ = timezone(timedelta(hours=8))
UDB = 'https://udb.moe.edu.tw'
DOWNLOAD = UDB + '/ulist/Resource/download/'
URLS = {
    'schools': DOWNLOAD + 'ulistaddress?extension=csv',
    'departments': DOWNLOAD + 'ulistdepartmentlist_college?extension=csv',
    'students': 'https://stats.moe.gov.tw/files/opendata/students.csv',
}
RAW_ROOT = BASE_DIR / 'data/raw/education'


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def norm(text):
    text = unicodedata.normalize('NFKC', str(text or ''))
    return re.sub(r'\s+', '', text).replace('台', '臺').replace('巿', '市')


def read_csv(content, required):
    """MOE exports have title rows; locate the real header by its field names."""
    for encoding in ('utf-8-sig', 'cp950'):
        try:
            rows = list(csv.reader(io.StringIO(content.decode(encoding))))
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('Cannot decode official CSV')
    for i, row in enumerate(rows[:10]):
        header = [x.strip() for x in row]
        if set(required).issubset(header):
            if len(set(header)) != len(header):
                raise ValueError('Duplicate CSV header')
            return [dict(zip(header, [v.strip() for v in row])) for row in rows[i+1:] if any(v.strip() for v in row)]
    raise ValueError(f'Official CSV schema changed; required: {required}')


def institution_links(content):
    soup = BeautifulSoup(content, 'html.parser')
    links = {urljoin(UDB, a['href']): a.get_text(' ', strip=True)
             for a in soup.select('a[href]') if '/ulist/Institution?' in a['href']}
    total = soup.select_one('#TotalItems')
    pages = soup.select_one('#TotalPages')
    if not total or not pages:
        raise ValueError('School search has no pagination metadata')
    return links, int(total['value']), int(pages['value'])


def parse_campuses(content):
    soup = BeautifulSoup(content, 'html.parser')
    heading = soup.select_one('h2.university-name')
    if not heading:
        raise ValueError('Institution page missing official heading')
    texts = [p.get_text(' ', strip=True) for p in soup.select('p')]
    result = []
    for i, text in enumerate(texts):
        if not text.startswith('校區：'):
            continue
        address = texts[i+1] if i+1 < len(texts) else ''
        if not address.startswith('地址：'):
            raise ValueError(f'Campus has no adjacent address: {text}')
        raw_address = address.removeprefix('地址：').strip()
        cleaned = norm(raw_address)
        city_match = re.search(r'[\u4e00-\u9fff]{2,3}[市縣]', cleaned)
        # Addresses begin with a postal code, followed by a county/city name.
        if not city_match:
            raise ValueError(f'Cannot parse county/city: {raw_address}')
        city = city_match.group(0)
        district = None
        if city == '臺中市':
            suffix = cleaned[city_match.end():]
            district = next((d for d in sorted(TAICHUNG_DISTRICTS, key=len, reverse=True) if suffix.startswith(d)), None)
            if not district:
                raise ValueError(f'Unknown Taichung district: {raw_address}')
        postal = re.match(r'\s*(\d{3,6})', raw_address)
        result.append({'name': text.removeprefix('校區：').strip(), 'address': raw_address,
                       'city': city, 'district': district, 'postal_code': postal.group(1) if postal else None})
    if not result:
        raise ValueError('No official campuses found; parser must be reviewed')
    return heading.get_text(' ', strip=True), result


def _source(folder, key, url, content, suffix, fetched_at=None):
    path = folder / (key + suffix)
    path.write_bytes(content)
    return {'source_key': key, 'url': url, 'fetched_at': fetched_at or now(),
            'sha256': digest(content), 'raw_path': str(path.relative_to(BASE_DIR))}


def download_bundle():
    folder = RAW_ROOT / datetime.now(TZ).strftime('%Y%m%dT%H%M%S%f')
    folder.mkdir(parents=True)
    sources = []
    for key, url in URLS.items():
        response = government_session().get(url, timeout=90)
        response.raise_for_status()
        sources.append(_source(folder, key, url, response.content, '.csv'))
    schools = read_csv((folder/'schools.csv').read_bytes(), ['學校代碼', '學校名稱', '學校地址'])
    parameters = {'Mode': '', 'Area': [], 'BuildType': [], 'InstitutionType': [],
                  'UniversityName': '', 'CollegeName': '', 'ISCEDId': [],
                  'DepartmentName': '', 'AcademicDegree': []}
    links = {}
    page = 1
    while True:
        url = UDB + f'/ulist/search?index={page}&limit=100'
        response = government_session().post(url, json=parameters, timeout=60)
        response.raise_for_status()
        sources.append(_source(folder, f'search-{page}', url, response.content, '.html'))
        found, total, pages = institution_links(response.content)
        if not found or not (set(found)-set(links)):
            raise ValueError('Pagination repeated or returned an empty page')
        links.update(found)
        if page >= pages:
            break
        page += 1
        if page > 100:
            raise ValueError('Unexpected school search pagination')
    if len(links) != total or total != len(schools):
        raise ValueError(f'School roster coverage mismatch: {len(links)}/{total}/{len(schools)}')
    print(f'Downloading {len(links)} national institution pages...', flush=True)
    def get_profile(pair):
        url, name = pair
        response = government_session().get(url, timeout=60)
        response.raise_for_status()
        actual, campuses = parse_campuses(response.content)
        if norm(actual) != norm(name):
            raise ValueError(f'Institution name mismatch: {name} / {actual}')
        key = 'institution-' + url.split('id=')[-1]
        return _source(folder, key, url, response.content, '.html')
    with ThreadPoolExecutor(max_workers=3) as pool:
        sources.extend(pool.map(get_profile, sorted(links.items())))
    manifest = {'retrieved_at': now(), 'parser_version': VERSION, 'national_school_count': total,
                'request': parameters, 'sources': sources}
    (folder/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return folder


def load_bundle(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    contents = {}
    for source in manifest['sources']:
        file = (BASE_DIR/source['raw_path']).resolve()
        if not file.is_relative_to(RAW_ROOT.resolve()):
            raise ValueError('Source file outside education raw directory')
        content = file.read_bytes()
        if digest(content) != source['sha256']:
            raise ValueError(f'Source checksum mismatch: {source["source_key"]}')
        if source['source_key'] in contents:
            raise ValueError('Duplicate source key')
        contents[source['source_key']] = content
    return manifest, contents


def build_records(manifest, contents, academic_year=None):
    schools = read_csv(contents['schools'], ['學校代碼', '學校名稱', '學校地址'])
    departments = read_csv(contents['departments'], ['學校代碼', '系所代碼', '系所名稱'])
    students = read_csv(contents['students'], ['學年度', '學校代碼', '科系代碼', '科系名稱'])
    years = {int(r['學年度']) for r in students}
    registry_year = re.search(r'(\d{3})學年度', contents['schools'].decode('utf-8-sig').splitlines()[0])
    if not registry_year:
        raise ValueError('School roster academic year missing')
    year = int(registry_year.group(1))
    if academic_year is not None and year != academic_year:
        raise ValueError(f'Requested year {academic_year} differs from current roster {year}')
    if year not in years or f'{year}學年度' not in contents['departments'].decode('utf-8-sig').splitlines()[0]:
        raise ValueError('Official sources do not share an academic year')
    by_name = {norm(s['學校名稱']): s for s in schools}
    if len(by_name) != len(schools):
        raise ValueError('Duplicate institution name in official roster')
    school_by_code = {s['學校代碼'].zfill(4): s for s in schools}
    if len(school_by_code) != len(schools):
        raise ValueError('Duplicate institution code')
    profiles, campuses = {}, []
    for key, content in sorted(contents.items()):
        if not key.startswith('institution-'):
            continue
        name, rows = parse_campuses(content)
        school = by_name.get(norm(name))
        if not school:
            raise ValueError(f'Institution profile not in national roster: {name}')
        code = school['學校代碼'].zfill(4)
        if code in profiles:
            raise ValueError('Duplicate institution profile')
        profiles[code] = key
        for row in rows:
            row.update(institution_id=code, source_key=key)
            # Some schools report several sites under the same campus label.
            identity = norm(row['name']) + '|' + norm(row['address'])
            row['campus_id'] = code + ':' + digest(identity.encode())[:16]
            campuses.append(row)
    if len(profiles) != len(schools) or len(schools) != manifest['national_school_count']:
        raise ValueError('National campus profile coverage incomplete')
    if len({r['campus_id'] for r in campuses}) != len(campuses):
        raise ValueError('Duplicate campus name/address within an institution')
    scope = {r['institution_id'] for r in campuses if r['city'] == '臺中市'}
    headquarters_scope = {s['學校代碼'].zfill(4) for s in schools if norm(s['縣市別']) == '臺中市'}
    if not headquarters_scope.issubset(scope):
        raise ValueError('Taichung-headquartered school has no parsed Taichung campus')
    dept_by_id = {}
    for row in departments:
        code = row['學校代碼'].zfill(4)
        if code not in scope:
            continue
        dep_code = row['系所代碼'].zfill(8)
        # Official department codes can be shared by distinct degree programmes.
        # Keep every named organisational unit instead of merging by code alone.
        key = code + ':' + dep_code + ':' + digest(norm(row['系所名稱']).encode())[:16]
        record = {'department_id': key, 'institution_id': code, 'department_code': dep_code,
                  'name': row['系所名稱'], 'college': row['學院名稱'],
                  'website': row.get('系所網址', ''), 'source_key': 'departments', 'registry_listed': 1}
        if key in dept_by_id and dept_by_id[key]['college'] != record['college']:
            colleges = set(dept_by_id[key]['college'].split('；')) | {record['college']}
            dept_by_id[key]['college'] = '；'.join(sorted(colleges))
        else:
            dept_by_id.setdefault(key, record)
    for row in students:
        code = row['學校代碼'].zfill(4)
        if int(row['學年度']) != year or code not in scope:
            continue
        dep_code = row['科系代碼'].zfill(8)
        candidates = [d for d in dept_by_id.values() if d['registry_listed']
                      and d['institution_id'] == code and d['department_code'] == dep_code]
        exact = [d for d in candidates if norm(d['name']) == norm(row['科系名稱'])]
        matched = exact[0] if len(exact) == 1 else (candidates[0] if len(candidates) == 1 else None)
        dep_id = matched['department_id'] if matched else (code + ':' + dep_code + ':' + digest(norm(row['科系名稱']).encode())[:16])
        if dep_id not in dept_by_id:
            # Supplement department names without storing any student counts.
            # A name absent from the current roster may no longer admit students.
            dept_by_id[dep_id] = {'department_id': dep_id, 'institution_id': code,
                'department_code': dep_code, 'name': row['科系名稱'], 'college': '',
                'website': '', 'source_key': 'students', 'registry_listed': 0}
    if not dept_by_id or not scope:
        raise ValueError('Empty Taichung education data')
    relations, tasks = [], []
    for dep in dept_by_id.values():
        school_campuses = [c for c in campuses if c['institution_id'] == dep['institution_id']]
        if len(school_campuses) == 1:
            c = school_campuses[0]
            relations.append({'department_id': dep['department_id'], 'campus_id': c['campus_id'],
                              'relation_type': 'SINGLE_OFFICIAL_CAMPUS', 'source_key': c['source_key']})
        else:
            tasks.append({'entity_id': dep['department_id'], 'task_type': 'DEPARTMENT_CAMPUS',
                          'reason': '學校官方列出多校區；尚無科系教學校區證據，不自動套用校本部。'})
        if not dep['registry_listed']:
            tasks.append({'entity_id': dep['department_id'], 'task_type': 'SUPPLEMENTARY_DEPARTMENT',
                          'reason': '當期學生統計仍有記錄，但系所組織名冊未列出；保留並待查，不能直接宣稱仍招生。'})
    for campus in campuses:
        if campus['institution_id'] in scope and campus['city'] == '臺中市':
            tasks.append({'entity_id': campus['campus_id'], 'task_type': 'COORDINATES',
                          'reason': '教育部校區頁提供地址，未提供核驗座標；保留 null，不推測經緯度。'})
    institutions = []
    urls = {s['source_key']: s['url'] for s in manifest['sources']}
    for code, row in school_by_code.items():
        institutions.append({'institution_id': code, 'name': row['學校名稱'],
            'school_type': row['體制'], 'ownership': row['公私立'],
            'headquarters_address': row['學校地址'], 'website': row['網址'],
            'profile_url': urls[profiles[code]], 'in_taichung_scope': int(code in scope)})
    summary = {'academic_year': year, 'national_institutions': len(institutions),
               'national_profiles_checked': len(profiles), 'national_campuses': len(campuses),
               'taichung_institutions': len(scope), 'taichung_headquartered_institutions': len(headquarters_scope),
               'taichung_campuses': sum(c['city'] == '臺中市' for c in campuses),
               'departments': len(dept_by_id), 'registry_departments': sum(d['registry_listed'] for d in dept_by_id.values()),
               'supplementary_departments': sum(not d['registry_listed'] for d in dept_by_id.values()),
               'single_campus_relations': len(relations),
               'verified_teaching_relations': 0, 'pending_department_campus': sum(t['task_type'] == 'DEPARTMENT_CAMPUS' for t in tasks),
               'verified_coordinates': 0, 'pending_coordinates': sum(t['task_type'] == 'COORDINATES' for t in tasks),
               'directory_status': 'OFFICIAL_DIRECTORY_IMPORTED', 'location_status': 'PARTIAL',
               'source_scope': f'{year}學年度教育部正式校區名冊；不含未列入名冊的推廣據點或空大學習中心。',
               'limitations': ['校區地址為教育部當期名冊所載，並非現地勘查。',
                   '單一官方校區關聯是可回溯推定，不等同逐系教學校區核驗。',
                   '學生統計的縣市欄位不能證明個別科系的實際上課校區。',
                   '未建立職類對照；科系名稱文字檢索不等於職位相關性推薦。']}
    return {'academic_year': year, 'institutions': institutions, 'campuses': campuses,
            'departments': list(dept_by_id.values()),
            'relations': relations, 'tasks': tasks, 'summary': summary}


def import_bundle(folder, db_path=DB_PATH, academic_year=None):
    manifest, contents = load_bundle(folder)
    data = build_records(manifest, contents, academic_year)
    signature = json.dumps({'parser': VERSION, 'year': data['academic_year'],
        'sources': sorted((s['source_key'], s['sha256']) for s in manifest['sources'])}, sort_keys=True).encode()
    release_id = 'edu-' + digest(signature)[:24]
    connection = sqlite3.connect(str(db_path))
    backup_path = None
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='education_releases'").fetchone():
            existing = connection.execute('SELECT summary_json FROM education_releases WHERE release_id=?', (release_id,)).fetchone()
            if existing:
                return {'release_id': release_id, 'already_imported': True, **json.loads(existing[0])}
        if Path(db_path).resolve() == DB_PATH.resolve():
            backup_dir = BASE_DIR/'data/backups/education'
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir/('before-education-' + datetime.now(TZ).strftime('%Y%m%dT%H%M%S%f') + '.db')
            with closing(sqlite3.connect(str(backup_path))) as backup:
                connection.backup(backup)
        connection.executescript((BASE_DIR/'database/education_schema.sql').read_text(encoding='utf-8'))
        with connection:
            existing = connection.execute('SELECT summary_json FROM education_releases WHERE release_id=?', (release_id,)).fetchone()
            if existing:
                return {'release_id': release_id, 'already_imported': True, **json.loads(existing[0])}
            connection.execute('INSERT INTO education_releases VALUES (?,?,?,?,?,?)',
                (release_id, data['academic_year'], VERSION, now(), f"{data['academic_year']}學年度，來源標準日為10月15日", json.dumps(data['summary'], ensure_ascii=False)))
            connection.executemany('INSERT INTO education_sources VALUES (?,?,?,?,?,?)',
                [(release_id, s['source_key'], s['url'], s['fetched_at'], s['sha256'], s['raw_path']) for s in manifest['sources']])
            def insert(table, records):
                if not records:
                    return
                columns = list(records[0])
                sql = f'INSERT INTO {table} (release_id,{",".join(columns)}) VALUES ({",".join("?" for _ in range(len(columns)+1))})'
                connection.executemany(sql, [(release_id, *(row[c] for c in columns)) for row in records])
            insert('education_institutions', data['institutions'])
            insert('education_campuses', [dict(c, latitude=None, longitude=None, address_status='OFFICIAL_REPORTED', coordinate_status='PENDING') for c in data['campuses']])
            insert('education_departments', data['departments'])
            insert('education_department_campuses', data['relations'])
            insert('education_review_tasks', [dict(t, task_id=digest((t['entity_id']+':'+t['task_type']).encode())[:24]) for t in data['tasks']])
            if connection.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Foreign key validation failed')
            connection.execute('INSERT INTO education_active_release VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET release_id=excluded.release_id', (release_id,))
        return {'release_id': release_id, 'already_imported': False,
                'backup_path': str(backup_path) if backup_path else None, **data['summary']}
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', type=Path, help='Use a checksummed manifest folder without network')
    parser.add_argument('--db', type=Path, default=DB_PATH)
    parser.add_argument('--academic-year', type=int)
    args = parser.parse_args()
    folder = args.offline or download_bundle()
    result = import_bundle(folder, args.db, args.academic_year)
    result['database_path'] = str(args.db.resolve())
    result['manifest_path'] = str(folder/'manifest.json')
    report = BASE_DIR/'reports/education_directory_import.json'
    if result['already_imported'] and report.exists():
        previous = json.loads(report.read_text(encoding='utf-8'))
        if (previous.get('release_id') == result['release_id']
                and previous.get('database_path') == result['database_path']
                and previous.get('backup_path')):
            result['backup_path'] = previous['backup_path']
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
