"""Read-only checks for the minimal campus delivery; raw sources are not bundled."""
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.education_directory import education_db_path, get_education_coverage, search_education_campuses
from engine.campus_details import campus_detail

def verify():
    path = education_db_path().resolve()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        assert conn.execute('SELECT COUNT(*) FROM education_releases').fetchone()[0] == 1
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='education_programs'").fetchone()
        assert all(r[0].startswith('education_') for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    coverage = get_education_coverage()
    result = search_education_campuses(24.15, 120.65, 1000)
    assert result['total'] == 22
    assert len({r['institution_id'] for r in result['items']}) == 17
    assert len({r['institution_id'] for r in result['items'] if r['school_phone']['status'] == 'AVAILABLE'}) == 17
    for item in result['items']:
        assert item['coordinate_status'] == 'VERIFIED_OFFICIAL_GEOMETRY'
        assert item['coordinate_reference']['crs'] == 'EPSG:4326'
        assert item['school_phone']['kind'] == 'INSTITUTION_SWITCHBOARD'
        assert item['school_phone']['source_url'].startswith('https://udb.moe.edu.tw/')
    query = search_education_campuses(24.15, 120.65, 30, '資工系', include_related=True)
    assert query['query_expansion']['department_terms'] == ['資訊工程']
    assert query['total'] > 0
    detail = campus_detail(query['items'][0]['campus_id'], query['release_id'])
    assert detail['release_id'] == coverage['release_id']
    assert set(detail) == {'release_id', 'academic_year', 'campus'}
    from engine.education_directory import search_education_departments
    departments = search_education_departments(q='資訊')
    assert all('programs' not in item for item in departments['items'])
    assert 'programs' not in coverage
    from api.education import router
    from fastapi import FastAPI
    app = FastAPI(); app.include_router(router)
    assert len(app.openapi()['paths']) == 5
    assert before == hashlib.sha256(path.read_bytes()).hexdigest()
    return {'integrity': 'ok', 'institutions': 17, 'campuses': 22, 'switchboards': 17,
            'release_id': coverage['release_id'], 'sha256': before, 'read_only': True,
            'raw_source_files_rechecked': False}

if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
