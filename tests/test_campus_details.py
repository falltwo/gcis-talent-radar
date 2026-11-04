"""Campus details and scoped department search without statistics interfaces."""
import sqlite3
import unittest
from contextlib import closing
from tests import test_campus_map_api as fixtures
from tests.test_campus_map_api import api_get
from engine.campus_details import campus_detail, EducationEntityNotFound
from engine.education_directory import search_education_campuses, search_education_departments


class CampusDetailsTests(unittest.TestCase):
    setUp = fixtures.CampusMapTests.setUp

    def test_detail_contains_only_campus_identity_and_provenance(self):
        detail = campus_detail('a1', 'current')
        self.assertEqual(set(detail), {'release_id', 'academic_year', 'campus'})
        self.assertEqual(detail['campus']['institution_name'], '甲大學')
        self.assertEqual(detail['campus']['coordinate_reference']['crs'], 'EPSG:4326')
        self.assertTrue(detail['campus']['departments'][0]['relation_source_url'])
        self.assertNotIn('insights', detail)
        self.assertNotIn('enrollment_size', str(detail))
        self.assertNotIn('employer_preference', str(detail))

    def test_detail_route_preserves_not_found_and_version_errors(self):
        code, detail = api_get(self.app, {'release_id': 'current'}, '/api/education/campuses/a1')
        self.assertEqual(code, 200)
        self.assertEqual(set(detail), {'release_id', 'academic_year', 'campus'})
        self.assertEqual(api_get(self.app, {}, '/api/education/campuses/missing')[0], 404)
        self.assertEqual(api_get(self.app, {'release_id': 'missing'}, '/api/education/campuses/a1')[0], 503)
        with self.assertRaises(EducationEntityNotFound):
            campus_detail('missing')

    def test_removed_statistics_endpoint_is_not_published(self):
        self.assertEqual(api_get(self.app, {}, '/api/education/institutions/a/department-insights')[0], 404)
        paths = self.app.openapi()['paths']
        self.assertEqual(len(paths), 5)
        self.assertFalse(any('department-insights' in path for path in paths))

    def test_department_directory_does_not_require_or_return_statistics(self):
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='education_programs'").fetchone())
        result = search_education_departments(q='資訊', db_path=self.path)
        self.assertEqual(result['total'], 1)
        self.assertNotIn('programs', result['items'][0])
        self.assertNotIn('enrolled_students', str(result))
        self.assertNotIn('popularity', str(result))
        self.assertNotIn('employer_preference', str(result))

    def test_related_results_separate_and_do_not_change_radius(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('INSERT INTO education_departments VALUES (?,?,?,?,?,?,?,?,?)',('current','im','a','im','資訊管理學系','管理學院','https://a.example','departments',1))
        kwargs=dict(latitude=24.15,longitude=120.65,q='資工',radius_km=5)
        direct=search_education_campuses(**kwargs)
        expanded=search_education_campuses(**kwargs,include_related=True)
        self.assertEqual({r['campus_id'] for r in direct['items']},{'b1','b2'})
        self.assertEqual(expanded['items'][-1]['campus_id'],'a1')
        self.assertEqual(expanded['items'][-1]['match_tier'],'RELATED')
        self.assertEqual(expanded['items'][-1]['matched_departments'],[])
        self.assertEqual(expanded['radius_km'],5)
        self.assertTrue(expanded['search_rule_version'])
        typo=search_education_campuses(24.15,120.65,q='資訊攻程',radius_km=.1)
        self.assertEqual(typo['total'],0)
        self.assertTrue(any('資訊工程' in s for s in typo['suggestions']))
