"""Real parser and transaction tests, isolated from the project's populated DB."""
import csv
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from etl import load_education_directory as loader
from engine.education_directory import get_education_coverage, list_education_institutions, search_education_departments


def export_csv(header, rows, title=None):
    s = io.StringIO()
    w = csv.writer(s)
    if title:
        w.writerow([title])
    w.writerow(header)
    w.writerows(rows)
    return s.getvalue().encode('utf-8-sig')


class EducationDirectoryTests(unittest.TestCase):
    def setUp(self):
        loader.RAW_ROOT.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(prefix='fixture-', dir=loader.RAW_ROOT)
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.db_path = self.folder/'test.db'
        self.contents = {
            'schools': export_csv(['學校代碼','學校名稱','學校地址','縣市別','體制','公私立','網址'], [
                ['0001','甲大學','臺中市西屯區甲路1號','臺中市','一般大學','公立','https://a.edu.tw'],
                ['0002','乙大學','臺北市中正區乙路1號','臺北市','一般大學','公立','https://b.edu.tw'],
                ['0003','丙大學','臺中市南區丙路1號','臺中市','技專校院','私立','https://c.edu.tw'],
            ], '114學年度全國名錄'),
            'departments': export_csv(['學校代碼','系所代碼','系所名稱','學院名稱','系所網址'], [
                ['0001','07151001','機械工程學系','工學院','https://a.edu.tw/me'],
                ['0002','07151001','機械工程學系','工學院','https://b.edu.tw/me'],
                ['0003','06131001','資訊工程系','資電學院','https://c.edu.tw/cs'],
            ], '114學年度大專校院系所彙整表'),
            'students': self.student_csv(),
            'institution-a': self.profile('甲大學', [('本部','407001臺中巿西屯區甲路1號')]),
            'institution-b': self.profile('乙大學', [('本部','100001臺北市中正區乙路1號'),('臺中分部','411001台中市太平區乙路2號')]),
            'institution-c': self.profile('丙大學', [('本部','402001臺中市南區丙路1號')]),
        }
        self.write_manifest()

    def student_csv(self, count=20):
        return export_csv(['學年度','學校代碼','科系代碼','科系名稱','日間∕進修別','等級別','縣市名稱','總計'], [
            ['114','1','7151001','機械工程學系','D 日','B 學士','19 臺中市',str(count)],
            ['114','1','7151001','機械工程學系','D 日','M 碩士','19 臺中市','8'],
            ['114','2','7151001','機械工程學系','D 日','B 學士','30 臺北市','9'],
            ['114','3','6131001','資訊工程系','D 日','B 學士','19 臺中市','0'],
            ['113','3','6131001','資訊工程系','D 日','B 學士','19 臺中市','99'],
        ])

    @staticmethod
    def profile(name, campuses):
        return ('<h2 class="university-name">'+name+'</h2>'+''.join(
            f'<p>校區：{c}</p><p>地址：{a}</p>' for c,a in campuses)).encode()

    def write_manifest(self):
        sources = [loader._source(self.folder, key, 'https://udb.moe.edu.tw/fixture/'+key,
            value, '.html' if key.startswith('institution-') else '.csv', '2026-11-02T10:00:00+08:00')
            for key,value in self.contents.items()]
        (self.folder/'manifest.json').write_text(json.dumps({'national_school_count':3,'sources':sources}), encoding='utf-8')

    def run_import(self):
        return loader.import_bundle(self.folder, self.db_path)

    def test_fcu_overseas_dual_degrees_are_excluded_from_import(self):
        self.contents['schools'] = self.contents['schools'].replace(b'0001', b'1007')
        self.contents['departments'] = self.contents['departments'].replace(b'0001', b'1007')
        self.contents['students'] = self.contents['students'].replace(b',1,', b',1007,')
        foreign = '澳洲昆士蘭大學電機工程雙學士學位學程'
        self.contents['departments'] += ('1007,07141044,'+foreign+',工學院,https://example.edu\r\n').encode()
        self.contents['students'] += ('114,1007,7141044,'+foreign+',D 日,B 學士,19 臺中市,20\r\n').encode()
        self.write_manifest()
        result = self.run_import()
        rows = search_education_departments(institution_id='1007', db_path=self.db_path)
        self.assertEqual([d['name'] for d in rows['items']], ['機械工程學系'])
        self.assertEqual(result['excluded_programs'], 1)

    def test_scope_cleanup_publishes_new_snapshot_and_preserves_original(self):
        original = self.run_import()['release_id']
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("INSERT INTO education_institutions SELECT release_id,'1007','逢甲大學',school_type,ownership,headquarters_address,website,profile_url,in_taichung_scope FROM education_institutions WHERE institution_id='0001'")
            conn.execute("INSERT INTO education_departments VALUES (?,?,?,?,?,?,?,?,?)",
                         (original,'foreign-degree','1007','test','澳洲昆士蘭大學電機工程雙學士學位學程','工學院','','departments',1))
        from etl.apply_education_program_scope import apply_scope
        result = apply_scope(self.db_path)
        self.assertEqual(result['removed_count'], 1)
        self.assertNotEqual(result['release_id'], original)
        self.assertEqual(search_education_departments(q='昆士蘭',db_path=self.db_path)['total'],0)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM education_departments WHERE release_id=? AND department_id='foreign-degree'",(original,)).fetchone()[0],1)
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(apply_scope(self.db_path)['removed_count'],0)

    def test_full_roster_scope_leading_zeroes_without_student_counts(self):
        result = self.run_import()
        # National scan includes a Taichung branch of a Taipei school.
        self.assertEqual(result['taichung_institutions'],3)
        self.assertEqual(result['taichung_headquartered_institutions'],2)
        self.assertNotIn('programs', result)
        self.assertEqual(result['departments'],3)
        self.assertEqual(result['pending_department_campus'],1)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM education_department_campuses').fetchone()[0],2)
            self.assertEqual(conn.execute("SELECT department_code FROM education_departments WHERE institution_id='0001'").fetchone()[0],'07151001')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM education_campuses WHERE latitude IS NOT NULL').fetchone()[0],0)
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
        schools = list_education_institutions(self.db_path)
        self.assertEqual(len(schools['items']),3)
        rows = search_education_departments(q='機械', db_path=self.db_path)
        self.assertEqual(rows['total'],2)
        self.assertNotIn('programs', rows['items'][0])
        # A same-school city field is not evidence for a teaching location.
        geographic = search_education_departments(q='機械',district='西屯區',db_path=self.db_path)
        self.assertEqual(geographic['status'],'NO_VERIFIED_LOCATION')
        self.assertEqual(search_education_departments(q="%' OR 1=1 --",db_path=self.db_path)['total'],0)

    def test_idempotent_import_does_not_duplicate(self):
        a = self.run_import()
        b = self.run_import()
        self.assertEqual(a['release_id'],b['release_id'])
        self.assertTrue(b['already_imported'])
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM education_releases').fetchone()[0],1)
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='education_programs'").fetchone())

    def test_bad_new_batch_rolls_back_and_keeps_active_snapshot(self):
        old = self.run_import()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("CREATE TRIGGER reject_bad_fixture BEFORE INSERT ON education_departments WHEN NEW.name='錯誤科系' BEGIN SELECT RAISE(ABORT,'fixture rejection'); END")
        self.contents['departments'] = self.contents['departments'].replace('機械工程學系'.encode(), '錯誤科系'.encode(), 1)
        self.write_manifest()
        with self.assertRaises(sqlite3.IntegrityError):
            self.run_import()
        self.assertEqual(get_education_coverage(self.db_path)['release_id'],old['release_id'])
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM education_releases').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM education_departments').fetchone()[0],3)

    def test_changed_raw_file_is_rejected_before_import(self):
        (self.folder/'students.csv').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'checksum'):
            self.run_import()
        self.assertFalse(self.db_path.exists())

    def test_missing_national_profile_fails_closed(self):
        del self.contents['institution-b']
        self.write_manifest()
        with self.assertRaisesRegex(ValueError,'coverage incomplete'):
            self.run_import()

    def test_year_mismatch_is_rejected_but_unused_counts_are_not_imported(self):
        with self.assertRaisesRegex(ValueError, 'Requested year'):
            loader.import_bundle(self.folder, self.db_path, 113)
        self.contents['students'] = self.student_csv('不提供人數')
        self.write_manifest()
        result = self.run_import()
        self.assertEqual(result['departments'], 3)
        self.assertNotIn('programs', result)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='education_programs'").fetchone())

    def test_unicode_compatibility_and_pagination_metadata(self):
        self.assertEqual(loader.norm('新北市林口區'),'新北市林口區')
        content=b'<a href="/ulist/Institution?id=x">a</a><input id="TotalItems" value="149"><input id="TotalPages" value="2">'
        links,total,pages=loader.institution_links(content)
        self.assertEqual((len(links),total,pages),(1,149,2))

    def test_shared_official_code_keeps_distinct_named_departments(self):
        self.contents['departments'] += b'0001,07151001,' + '機械工程碩士學位學程,工學院,https://a.edu.tw/me-master\r\n'.encode()
        self.write_manifest()
        result = self.run_import()
        self.assertEqual(result['registry_departments'],4)
        rows = search_education_departments(q='機械', institution_id='0001', db_path=self.db_path)['items']
        self.assertEqual(len(rows),2)
        self.assertTrue(all('programs' not in row for row in rows))

    def test_same_campus_label_with_different_addresses_is_preserved(self):
        self.contents['institution-b'] = self.profile('乙大學',[
            ('校本部','100001臺北市中正區乙路1號'),('校本部','411001臺中市太平區乙路2號')])
        self.write_manifest()
        result=self.run_import()
        self.assertEqual(result['national_campuses'],4)
        self.assertEqual(result['taichung_campuses'],3)


if __name__ == '__main__':
    unittest.main()
