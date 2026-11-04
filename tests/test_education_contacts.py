"""Official roster contacts: coverage, rollback, and versioned read-only APIs."""
import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from tests import test_campus_map_api as fixtures
from engine.education_directory import search_education_campuses, list_education_institutions
from engine.campus_details import campus_detail
from etl.load_education_contacts import import_contacts, normalize_phone, parse_roster, SOURCE_URL

ROOT = Path(__file__).resolve().parents[1]


class EducationContactTests(unittest.TestCase):
    setUp = fixtures.CampusMapTests.setUp

    def bundle(self, rows=None):
        handle=tempfile.TemporaryDirectory(prefix='contact-fixture-', dir=ROOT/'tmp')
        self.addCleanup(handle.cleanup)
        folder=Path(handle.name)
        out=io.StringIO();writer=csv.writer(out);writer.writerow(['114學年名錄']);writer.writerow(['學校代碼','學校名稱','學校總機','學校傳真'])
        writer.writerows(rows or [['a','甲大學','04-2451-7250','04-1111-1111'],['b','乙大學','(04) 2221-3108','04-2222-2222']])
        # The isolated fixture uses non-numeric IDs; make source keys exactly its IDs after zfill.
        raw=out.getvalue().encode('utf-8-sig');(folder/'schools.csv').write_bytes(raw)
        manifest={'source_url':SOURCE_URL,'sha256':hashlib.sha256(raw).hexdigest(),
                  'raw_path':str((folder/'schools.csv').relative_to(ROOT)),
                  'source_header':['114學年名錄'],'checked_at':'2026-11-03T12:00:00+08:00'}
        (folder/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        return folder

    def numeric_ids(self):
        # School IDs are numeric in the official source and production snapshot.
        with closing(sqlite3.connect(self.path)) as conn,conn:
            for table in ['education_institutions','education_campuses','education_departments']:
                conn.execute(f"UPDATE {table} SET institution_id=CASE institution_id WHEN 'a' THEN '0001' ELSE '0002' END")

    def test_complete_import_and_phone_types_are_not_confused_with_fax(self):
        self.numeric_ids();folder=self.bundle([['0001','甲大學','04-2451-7250','04-1111-1111'],['0002','乙大學','(04) 2221-3108','04-2222-2222']])
        result=import_contacts(folder,self.path);self.assertEqual(result['contacts_imported'],2)
        phones=search_education_campuses(24.15,120.65,db_path=self.path)['items']
        self.assertEqual(phones[0]['school_phone']['display'],'04-2451-7250')
        self.assertEqual(phones[0]['school_phone']['tel_uri'],'tel:+886424517250')
        self.assertEqual(phones[0]['school_phone']['kind'],'INSTITUTION_SWITCHBOARD')
        self.assertEqual(campus_detail('b1',db_path=self.path)['campus']['school_phone']['tel_uri'],'tel:+886422213108')
        self.assertEqual(list_education_institutions(self.path)['items'][0]['school_phone']['checked_at'],'2026-11-03T12:00:00+08:00')
        import_contacts(folder,self.path)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM education_institution_contacts').fetchone()[0],2)
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_bad_or_missing_school_aborts_without_creating_contacts(self):
        self.numeric_ids()
        for rows in [[['0001','甲大學','04-2451-7250','']], [['0001','甲大學','04-2451-7250',''],['0002','乙大學','無','']], [['0001','錯校名','04-2451-7250',''],['0002','乙大學','04-2221-3108','']]]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):import_contacts(self.bundle(rows),self.path)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertFalse(conn.execute("SELECT 1 FROM sqlite_master WHERE name='education_institution_contacts'").fetchone())

    def test_missing_contacts_or_other_release_never_fabricates_a_phone(self):
        result=search_education_campuses(24.15,120.65,db_path=self.path)
        self.assertEqual(result['items'][0]['school_phone']['status'],'UNAVAILABLE')
        self.assertIsNone(result['items'][0]['school_phone']['tel_uri'])
        self.assertEqual(normalize_phone('04-2451-7250'),('04-2451-7250','+886424517250'))
        for value in ['javascript:alert(1)','傳真04-1111-1111','04-1234-5678#20','']:
            with self.subTest(value=value),self.assertRaises(ValueError):normalize_phone(value)
        with self.assertRaises(ValueError):parse_roster(b'no phone column')

    def test_invalid_update_or_tampered_source_keeps_published_contacts(self):
        self.numeric_ids()
        valid=[['0001','甲大學','04-2451-7250',''],['0002','乙大學','04-2221-3108','']]
        folder=self.bundle(valid);import_contacts(folder,self.path)
        bad=self.bundle([['0001','甲大學','04-1111-1111',''],['0002','乙大學','無','']])
        with self.assertRaises(ValueError):import_contacts(bad,self.path)
        (folder/'schools.csv').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'checksum'):import_contacts(folder,self.path)
        result=search_education_campuses(24.15,120.65,db_path=self.path)
        self.assertEqual(result['items'][0]['school_phone']['display'],'04-2451-7250')
