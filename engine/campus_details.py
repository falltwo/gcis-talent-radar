"""Read-only campus identity, department relations, coordinates, and switchboard."""
from engine.education_contacts import read_institution_contacts, missing_phone
from engine.education_directory import directory_connection, _release, _coordinate_references


class EducationEntityNotFound(ValueError):
    pass


def campus_detail(campus_id, release_id=None, db_path=None):
    with directory_connection(db_path) as conn:
        release = _release(conn, release_id)
        rid = release['release_id']
        campus = conn.execute('''SELECT c.*,i.name AS institution_name,i.website,s.url AS source_url
            FROM education_campuses c JOIN education_institutions i USING(release_id,institution_id)
            JOIN education_sources s ON s.release_id=c.release_id AND s.source_key=c.source_key
            WHERE c.release_id=? AND c.campus_id=? AND c.city='臺中市' AND i.in_taichung_scope=1''', (rid, campus_id)).fetchone()
        if not campus:
            raise EducationEntityNotFound('找不到此版本的校區')
        item = dict(campus)
        item['school_phone'] = read_institution_contacts(conn, rid).get(item['institution_id'], missing_phone())
        item['coordinate_reference'] = _coordinate_references(conn, rid).get(campus_id)
        item['departments'] = [dict(row) for row in conn.execute('''SELECT d.department_id,d.name,d.website,r.relation_type,s.url AS relation_source_url
            FROM education_department_campuses r JOIN education_departments d USING(release_id,department_id)
            JOIN education_sources s ON s.release_id=r.release_id AND s.source_key=r.source_key
            WHERE r.release_id=? AND r.campus_id=? ORDER BY d.name''', (rid, campus_id))]
        return {'release_id': rid, 'academic_year': release['academic_year'], 'campus': item}
