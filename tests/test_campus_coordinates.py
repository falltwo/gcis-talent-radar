"""Synthetic official-shaped geometry; no network or project DB mutations."""
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from zipfile import ZipFile

from etl import enrich_campus_coordinates as geo
from etl.load_education_directory import _source
from engine.education_directory import get_education_coverage,list_education_institutions
import tests.test_education_directory as directory_fixtures


class CampusCoordinateTests(unittest.TestCase):
    def setUp(self):
        fixture=directory_fixtures.EducationDirectoryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture=fixture
        self.parent=fixture.run_import()
        self.db=fixture.db_path
        geo.COORD_ROOT.mkdir(parents=True,exist_ok=True)
        temp=tempfile.TemporaryDirectory(prefix='fixture-',dir=geo.COORD_ROOT)
        self.addCleanup(temp.cleanup)
        self.folder=Path(temp.name)
        parent,campuses=geo.active_snapshot(self.db)
        self.campuses=campuses
        self.selection={'matches':[]}
        shapefile,CRS,Transformer,_,_=geo.geo_modules()
        shp,shx,dbf=io.BytesIO(),io.BytesIO(),io.BytesIO()
        writer=shapefile.Writer(shp=shp,shx=shx,dbf=dbf,shapeType=shapefile.POLYGON,encoding='utf-8')
        for name,kind,size in [('OBJECTID','N',9),('BLOCKTYPE','N',4),('BLOCKNAME','C',100),('YYYYMM','C',8)]:
            writer.field(name,kind,size)
        to_projected=Transformer.from_crs(4326,3826,always_xy=True)
        for i,campus in enumerate(campuses):
            oid=i+1
            name=campus['institution_name']+campus['name']
            x,y=to_projected.transform(120.65+i*.01,24.15)
            writer.poly([[(x-40,y-40),(x-40,y+40),(x+40,y+40),(x+40,y-40),(x-40,y-40)]])
            writer.record(oid,1,name,'202601')
            self.selection['matches'].append({'campus_id':campus['campus_id'],'object_id':oid,'feature_name':name,'note':'Fixture campus exact match'})
        writer.close()
        zipped=io.BytesIO()
        with ZipFile(zipped,'w') as z:
            for ext,data in [('shp',shp.getvalue()),('shx',shx.getvalue()),('dbf',dbf.getvalue()),('prj',CRS.from_epsg(3826).to_wkt().encode()),('cpg',b'UTF-8')]:
                z.writestr('schools.'+ext,data)
        self.zip_bytes=zipped.getvalue()
        self.points=geo.derive_points(self.zip_bytes,self.selection,campuses)
        self.sources=[_source(self.folder,'coordinates-nlsc-school-polygons','https://www.tgos.tw/fixture.zip',self.zip_bytes,'.zip'),
                      _source(self.folder,'coordinates-selection','urn:fixture',json.dumps(self.selection,ensure_ascii=False).encode(),'.json')]
        for point in self.points:
            url=f"https://api.nlsc.gov.tw/other/TownVillagePointQuery1/{point['longitude']:.8f}/{point['latitude']:.8f}/4326"
            xml=f"<townVillageItem><ctyName>臺中市</ctyName><townName>{point['district']}</townName></townVillageItem>".encode()
            source=_source(self.folder,point['validation_source_key'],url,xml,'.xml')
            self.sources.append(source)
            point['administrative_validation']=geo.validate_district(point,xml)
            point['verified_at']=source['fetched_at']
        self.manifest={'version':geo.VERSION,'parent_release_id':parent['release_id'],'sources':self.sources,'points':self.points}
        self.save()

    def save(self):
        (self.folder/'manifest.json').write_text(json.dumps(self.manifest,ensure_ascii=False),encoding='utf-8')

    def test_publish_all_points_preserves_parent_and_provides_api_provenance(self):
        result=geo.import_coordinates(self.folder,self.db)
        self.assertEqual(result['verified_coordinates'],3)
        self.assertEqual(result['pending_coordinates'],0)
        self.assertEqual(get_education_coverage(self.db)['release_id'],result['release_id'])
        schools=list_education_institutions(self.db)['items']
        local=[c for s in schools for c in s['campuses'] if c['city']=='臺中市']
        self.assertEqual(len(local),3)
        for campus in local:
            self.assertTrue(campus['latitude'])
            self.assertEqual(campus['coordinate_reference']['point_type'],'CAMPUS_INTERIOR_REFERENCE')
            self.assertEqual(campus['coordinate_reference']['crs'],'EPSG:4326')
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM education_campuses WHERE release_id=? AND latitude IS NOT NULL',(self.parent['release_id'],)).fetchone()[0],0)
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='education_programs'").fetchone())
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM education_review_tasks WHERE release_id=? AND task_type='DEPARTMENT_CAMPUS'",(result['release_id'],)).fetchone()[0],1)
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
        repeat=geo.import_coordinates(self.folder,self.db)
        self.assertTrue(repeat['already_imported'])
        self.assertEqual(repeat['release_id'],result['release_id'])

    def test_refresh_publishes_new_sources_without_changing_parent(self):
        first = geo.import_coordinates(self.folder, self.db)
        first_id = first['release_id']
        with closing(sqlite3.connect(self.db)) as conn:
            first_sources = dict(conn.execute(
                'SELECT source_key,sha256 FROM education_sources WHERE release_id=?', (first_id,)))

        self.folder = self.folder / 'refresh'
        self.folder.mkdir()
        self.manifest['parent_release_id'] = first_id
        self.selection['matches'][0]['note'] = 'Updated match rationale'
        self.points[0]['match_note'] = 'Updated match rationale'
        selection = _source(self.folder, 'coordinates-selection', 'urn:fixture',
                            json.dumps(self.selection, ensure_ascii=False).encode(), '.json')
        self.sources[1] = selection
        self.save()

        refreshed = geo.import_coordinates(self.folder, self.db)
        refreshed_id = refreshed['release_id']
        self.assertNotEqual(refreshed_id, first_id)
        self.assertEqual(refreshed['parent_release_id'], first_id)
        self.assertEqual(get_education_coverage(self.db)['release_id'], refreshed_id)
        with closing(sqlite3.connect(self.db)) as conn:
            previous_sources = dict(conn.execute(
                'SELECT source_key,sha256 FROM education_sources WHERE release_id=?', (first_id,)))
            current_sources = dict(conn.execute(
                'SELECT source_key,sha256 FROM education_sources WHERE release_id=?', (refreshed_id,)))
            self.assertEqual(previous_sources, first_sources)
            self.assertNotEqual(selection['sha256'], first_sources['coordinates-selection'])
            self.assertEqual(current_sources, {**first_sources, 'coordinates-selection': selection['sha256']})
            self.assertEqual(conn.execute(
                'SELECT COUNT(*) FROM education_coordinate_evidence WHERE release_id=?',
                (refreshed_id,)).fetchone()[0], len(self.points))
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_coordinate_tampering_is_rejected_before_write(self):
        self.manifest['points'][0]['latitude']+=.1
        self.save()
        with self.assertRaisesRegex(ValueError,'differs from recomputed'):
            geo.import_coordinates(self.folder,self.db)
        self.assertEqual(get_education_coverage(self.db)['release_id'],self.parent['release_id'])

    def test_incomplete_selection_and_shared_polygon_are_rejected(self):
        partial={'matches':self.selection['matches'][:-1]}
        with self.assertRaisesRegex(ValueError,'cover every'):
            geo.derive_points(self.zip_bytes,partial,self.campuses)
        duplicate=json.loads(json.dumps(self.selection))
        duplicate['matches'][1]['object_id']=duplicate['matches'][0]['object_id']
        with self.assertRaisesRegex(ValueError,'multiple campuses'):
            geo.derive_points(self.zip_bytes,duplicate,self.campuses)

    def test_district_mismatch_and_missing_admin_data_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'Administrative mismatch'):
            geo.validate_district(self.points[0],b'<townVillageItem><ctyName>New Taipei</ctyName><townName>Unknown</townName></townVillageItem>')
        with self.assertRaisesRegex(ValueError,'no city or district'):
            geo.parse_district(b'<townVillageItem/>')

    def test_unrecognised_feature_name_is_rejected(self):
        wrong=json.loads(json.dumps(self.selection))
        wrong['matches'][0]['feature_name']='Wrong school'
        with self.assertRaisesRegex(ValueError,'changed identity'):
            geo.derive_points(self.zip_bytes,wrong,self.campuses)

    def test_failed_publication_rolls_back_coordinates_and_active_release(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TRIGGER reject_coordinate_fixture BEFORE INSERT ON education_coordinate_evidence BEGIN SELECT RAISE(ABORT,'coordinate fixture rejection'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            geo.import_coordinates(self.folder,self.db)
        self.assertEqual(get_education_coverage(self.db)['release_id'],self.parent['release_id'])
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM education_releases').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM education_coordinate_evidence').fetchone()[0],0)


if __name__=='__main__':
    unittest.main()
