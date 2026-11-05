"""Campus map contract tests: isolated SQLite, no network or production writes."""
import json
import math
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi import FastAPI
from api.education import router
from engine.education_directory import (
    EducationDataUnavailable, get_education_coverage, search_education_campuses,
)

ROOT = Path(__file__).resolve().parents[1]


def api_get(app, params, path='/api/education/campuses'):
    messages = []

    async def inline(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    async def exchange():
        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}

        async def send(message):
            messages.append(message)

        await app({'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
                   'http_version': '1.1', 'method': 'GET', 'scheme': 'http',
                   'path': path, 'raw_path': path.encode(),
                   'root_path': '', 'query_string': urlencode(params).encode(), 'headers': [],
                   'client': ('test', 1000), 'server': ('test', 80)}, receive, send)

    # All endpoints are synchronous SQLite reads. Step the ASGI coroutine
    # without a Windows event loop/socketpair; validation and routing still run.
    with patch('fastapi.routing.run_in_threadpool', inline), patch('fastapi.dependencies.utils.run_in_threadpool', inline):
        coroutine = exchange()
        try:
            coroutine.send(None)
        except StopIteration:
            pass
        else:
            raise AssertionError('Synchronous campus API unexpectedly requested async IO')
        finally:
            coroutine.close()
    status = next(message['status'] for message in messages if message['type'] == 'http.response.start')
    body = json.loads(b''.join(message.get('body', b'') for message in messages if message['type'] == 'http.response.body'))
    return status, body


class CampusMapTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='campus-map-', dir=ROOT / 'tmp')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'directory.sqlite3'
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript((ROOT / 'database/education_schema.sql').read_text(encoding='utf-8'))
            conn.execute('INSERT INTO education_releases VALUES (?,?,?,?,?,?)',
                         ('current', 114, 'fixture', '2026-11-02', '114學年', '{"limitations": []}'))
            conn.execute('INSERT INTO education_active_release VALUES (1,?)', ('current',))
            for key in ['schools', 'departments', 'polygons', 'validation']:
                conn.execute('INSERT INTO education_sources VALUES (?,?,?,?,?,?)',
                             ('current', key, 'https://official.example/' + key, '2026-11-02', 'abc', key))
            for institution_id, name in [('a', '甲大學'), ('b', '乙大學')]:
                conn.execute('INSERT INTO education_institutions VALUES (?,?,?,?,?,?,?,?,?)',
                             ('current', institution_id, name, '一般大學', '公立', '臺中市',
                              'https://school.example/', 'https://official.example/profile', 1))
            for campus_id, institution_id, name, city, lon, status in [
                ('a1', 'a', '甲校區', '臺中市', 120.65, 'VERIFIED_OFFICIAL_GEOMETRY'),
                ('b1', 'b', '乙一校區', '臺中市', 120.66, 'VERIFIED_OFFICIAL_GEOMETRY'),
                ('b2', 'b', '乙二校區', '臺中市', 120.67, 'VERIFIED_OFFICIAL_GEOMETRY'),
                ('pending', 'a', '待核驗校區', '臺中市', 120.65, 'PENDING'),
                ('outside', 'a', '外縣市校區', '臺北市', 120.65, 'VERIFIED_OFFICIAL_GEOMETRY'),
                ('no-evidence', 'a', '沒有座標出處', '臺中市', 120.65, 'VERIFIED_OFFICIAL_GEOMETRY'),
            ]:
                conn.execute('INSERT INTO education_campuses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                             ('current', campus_id, institution_id, name, '臺中市西屯區校園路1號', city,
                              '西屯區', '407', 24.15, lon, 'OFFICIAL_REPORTED', status, 'schools'))
                if campus_id != 'no-evidence':
                    conn.execute('INSERT INTO education_coordinate_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                 ('current', campus_id, 'polygons', 'validation', 1, name, '202601',
                                  'EPSG:3826', 'EPSG:4326', 'representative_point', 'CAMPUS_INTERIOR_REFERENCE',
                                  1.0, 2.0, '2026-11-02', '{}'))
            for department_id, institution_id, name in [('me', 'a', '機械工程學系'), ('cs', 'b', '資訊工程學系')]:
                conn.execute('INSERT INTO education_departments VALUES (?,?,?,?,?,?,?,?,?)',
                             ('current', department_id, institution_id, department_id, name, '工學院',
                              'https://school.example/department', 'departments', 1))
            conn.execute('INSERT INTO education_department_campuses VALUES (?,?,?,?,?)',
                         ('current', 'me', 'a1', 'SINGLE_OFFICIAL_CAMPUS', 'schools'))
        self.environment = patch.dict(os.environ, {'EDUCATION_DB_PATH': str(self.path)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = FastAPI()
        self.app.include_router(router)

    def query(self, **kwargs):
        return search_education_campuses(24.15, 120.65, **kwargs)

    def test_school_and_department_query_prioritizes_named_school_before_distance(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE education_institutions SET name='逢甲大學' WHERE institution_id='b'")
            conn.execute("UPDATE education_departments SET name='電機工程學系'")
        for query in ('逢甲電機', '逢甲 電機', '逢甲大學電機', '逢甲'):
            with self.subTest(query=query):
                data = self.query(q=query, radius_km=50, include_related=True)
                self.assertTrue(data['items'])
                self.assertEqual(data['items'][0]['institution_name'], '逢甲大學')
                if '電機' in query:
                    departments = data['items'][0]['unlocated_department_matches']
                    self.assertEqual([d['name'] for d in departments], ['電機工程學系'])

    def test_common_school_alias_combines_with_ai_department(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE education_institutions SET name='國立臺中科技大學' WHERE institution_id='b'")
            conn.execute("UPDATE education_departments SET name='人工智慧應用工程學士學位學程' WHERE institution_id='b'")
        for query in ('中科大 ai', '中科大AI', '台中科大 人工智慧'):
            with self.subTest(query=query):
                data = self.query(q=query, radius_km=50, include_related=True)
                self.assertTrue(data['items'])
                first = data['items'][0]
                self.assertEqual(first['institution_name'], '國立臺中科技大學')
                self.assertEqual(first['unlocated_department_matches'][0]['name'], '人工智慧應用工程學士學位學程')

    def test_job_title_finds_direct_and_related_departments_in_the_same_search(self):
        title = '軟體設計工程師'
        school_evidence = {'title': title, 'source_url': 'https://school.example/careers'}
        field_evidence = {'title': title, 'source_url': 'https://field.example/careers'}
        index = (
            'fixture',
            {'cs': {'direct': [school_evidence], 'related': [field_evidence]},
             'me': {'related': [field_evidence]}},
            {title: title},
        )
        with patch('engine.campus_careers.career_index', return_value=index):
            params = {'latitude': 24.15, 'longitude': 120.65, 'radius_km': 1.5, 'q': '軟體工程師'}
            code, direct = api_get(self.app, params)
            _, expanded = api_get(self.app, {**params, 'include_related': 'true'})
            _, name = api_get(self.app, {**params, 'q': '資工'})

        self.assertEqual(code, 200)
        self.assertEqual(direct['search_type'], 'DEPARTMENT_CAREER')
        self.assertEqual(direct['career_query']['roles'], [title])
        self.assertEqual([row['campus_id'] for row in direct['items']], ['b1'])
        self.assertEqual([row['campus_id'] for row in expanded['items']], ['b1', 'a1'])
        first, second = expanded['items']
        self.assertEqual(first['unlocated_department_matches'][0]['career_matches'], [school_evidence])
        self.assertEqual(first['related_departments'], [])
        self.assertEqual(second['match_tier'], 'RELATED')
        self.assertEqual(second['related_departments'][0]['career_matches'], [field_evidence])
        self.assertEqual(name['search_type'], 'CAMPUS_AND_DEPARTMENT_NAME_TEXT')

    def test_only_verified_taichung_geometry_and_sorted_real_distances(self):
        result = self.query(radius_km=5)
        self.assertEqual(result['release_id'], 'current')
        self.assertEqual(result['academic_year'], 114)
        self.assertEqual([row['campus_id'] for row in result['items']], ['a1', 'b1', 'b2'])
        self.assertEqual(result['items'][0]['distance_km'], 0)
        self.assertEqual(result['items'][0]['longitude'], 120.65)
        self.assertEqual(result['items'][0]['coordinate_reference']['crs'], 'EPSG:4326')
        expected = 6371.0088 * 2 * math.asin(math.cos(math.radians(24.15)) * math.sin(math.radians(.01) / 2))
        self.assertAlmostEqual(result['items'][1]['distance_km'], expected, places=4)
        self.assertEqual(self.query(radius_km=.001)['total'], 1)
        self.assertEqual(result['items'][0]['source_url'], 'https://official.example/schools')

    def test_name_search_does_not_claim_unlocated_departments_at_a_campus(self):
        located = self.query(radius_km=5, q='機械')['items']
        self.assertEqual(len(located), 1)
        self.assertEqual(located[0]['departments'][0]['relation_type'], 'SINGLE_OFFICIAL_CAMPUS')
        self.assertIn('推定', located[0]['departments'][0]['relation_label'])
        unlocated = self.query(radius_km=5, q='資訊')['items']
        self.assertEqual(len(unlocated), 2)
        for campus in unlocated:
            self.assertEqual(campus['departments'], [])
            self.assertEqual(campus['unlocated_department_count'], 1)
            self.assertEqual(campus['match_scope'], 'INSTITUTION_DEPARTMENT_UNLOCATED')
            self.assertEqual(campus['unlocated_department_matches'][0]['name'], '資訊工程學系')
        self.assertEqual(self.query(radius_km=5, q="%' OR 1=1 --")['total'], 0)
        self.assertEqual(self.query(radius_km=5, q='乙 二 校 區')['total'], 1)

    def test_cs_abbreviation_matches_full_name_without_expanding_to_other_information_departments(self):
        # A has an explicitly related CS department; B's CS department remains
        # unlocated. Similar information-management names are not CS aliases.
        with closing(sqlite3.connect(self.path)) as conn, conn:
            for department_id, institution_id, name in [
                ('cs-located', 'a', '資訊工程系'),
                ('im-located', 'a', '資訊管理學系'),
                ('im-unlocated', 'b', '資訊管理學系'),
                ('information-only', 'b', '資訊學程'),
            ]:
                conn.execute('INSERT INTO education_departments VALUES (?,?,?,?,?,?,?,?,?)',
                             ('current', department_id, institution_id, department_id, name, '工學院',
                              'https://school.example/department', 'departments', 1))
            for department_id in ['cs-located', 'im-located']:
                conn.execute('INSERT INTO education_department_campuses VALUES (?,?,?,?,?)',
                             ('current', department_id, 'a1', 'SINGLE_OFFICIAL_CAMPUS', 'schools'))

        full = self.query(radius_km=5, q='資訊工程')
        self.assertEqual([item['campus_id'] for item in full['items']], ['a1', 'b1', 'b2'])
        self.assertFalse(full['query_expansion']['alias_applied'])
        for keyword in ['資工', '資工系', '　資　工　系　']:
            with self.subTest(keyword=keyword):
                result = self.query(radius_km=5, q=keyword)
                self.assertEqual([{k:v for k,v in item.items() if k!='match_reason'} for item in result['items']], [{k:v for k,v in item.items() if k!='match_reason'} for item in full['items']])
                self.assertEqual(result['query_expansion'], {
                    'input': keyword, 'department_terms': ['資訊工程'], 'alias_applied': True,
                })
                located, *unlocated = result['items']
                self.assertEqual(located['match_scope'], 'CAMPUS_DEPARTMENT_NAME')
                self.assertEqual([department['name'] for department in located['matched_departments']], ['資訊工程系'])
                for campus in unlocated:
                    self.assertEqual(campus['departments'], [])
                    self.assertEqual(campus['match_scope'], 'INSTITUTION_DEPARTMENT_UNLOCATED')
                    self.assertEqual([department['name'] for department in campus['unlocated_department_matches']], ['資訊工程學系'])
                    self.assertEqual(campus['unlocated_department_count'], 3)
                status, via_api = api_get(self.app, {'latitude': 24.15, 'longitude': 120.65,
                                                      'radius_km': 5, 'q': keyword})
                self.assertEqual(status, 200)
                self.assertEqual(via_api['items'], result['items'])
                self.assertEqual(via_api['query_expansion'], result['query_expansion'])

        # The small alias vocabulary must not turn arbitrary longer text into
        # either a department recommendation or a broad information search.
        unmatched = self.query(radius_km=5, q='資工系主任')
        self.assertEqual(unmatched['total'], 0)
        self.assertFalse(unmatched['query_expansion']['alias_applied'])

    def test_department_alias_does_not_replace_literal_school_or_campus_name_search(self):
        # A has only mechanical engineering, so its result must come from the
        # original name text rather than the expanded department term.
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('UPDATE education_institutions SET name=? WHERE institution_id=?', ('資工系研習大學', 'a'))
        result = self.query(radius_km=5, q='資工系')
        school = next(item for item in result['items'] if item['campus_id'] == 'a1')
        self.assertEqual(school['match_scope'], 'INSTITUTION_NAME')
        self.assertEqual(school['matched_departments'], [])
        self.assertNotIn('a1', [item['campus_id'] for item in self.query(radius_km=5, q='資訊工程')['items']])

        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('UPDATE education_institutions SET name=? WHERE institution_id=?', ('甲大學', 'a'))
            conn.execute('UPDATE education_campuses SET name=? WHERE campus_id=?', ('資工系教學園區', 'a1'))
        result = self.query(radius_km=5, q='資工系')
        campus = next(item for item in result['items'] if item['campus_id'] == 'a1')
        self.assertEqual(campus['match_scope'], 'CAMPUS_NAME')
        self.assertEqual(campus['matched_departments'], [])
        self.assertNotIn('a1', [item['campus_id'] for item in self.query(radius_km=5, q='資訊工程')['items']])

    def test_empty_results_keep_snapshot_metadata_and_limits(self):
        result = self.query(q='找不到這所學校')
        self.assertEqual(result['status'], 'NO_MATCH')
        self.assertEqual(result['items'], [])
        self.assertEqual(result['academic_year'], 114)
        self.assertTrue(any('通勤' in note for note in result['limitations']))

    def test_invalid_finite_values_and_ranges_are_rejected(self):
        for kwargs in [{'latitude': float('nan')}, {'latitude': 91}, {'longitude': -181},
                       {'radius_km': 0}, {'radius_km': -1}, {'radius_km': float('inf')},
                       {'q': 'a' * 81}, {'latitude': True}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                search_education_campuses(**{'latitude': 24.15, 'longitude': 120.65, **kwargs})

    def test_api_contract_and_error_statuses(self):
        status, result = api_get(self.app, {'latitude': 24.15, 'longitude': 120.65, 'q': '機械'})
        self.assertEqual(status, 200)
        self.assertEqual(result['total'], 1)
        for invalid in [{'latitude': 'nan'}, {'radius_km': 'inf'}, {'radius_km': '0'}, {'longitude': '200'}]:
            with self.subTest(invalid=invalid):
                status, _ = api_get(self.app, {'latitude': 24.15, 'longitude': 120.65, **invalid})
                self.assertEqual(status, 422)
        missing = self.path.with_name('not-imported.sqlite3')
        with patch.dict(os.environ, {'EDUCATION_DB_PATH': str(missing)}):
            status, result = api_get(self.app, {'latitude': 24.15, 'longitude': 120.65})
            self.assertEqual(status, 503)
            self.assertIn('detail', result)
        self.assertFalse(missing.exists())

    def test_wrong_or_missing_snapshot_fails_without_creating_mock_data(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('DELETE FROM education_active_release')
        with self.assertRaises(EducationDataUnavailable):
            self.query()


if __name__ == '__main__':
    unittest.main()
