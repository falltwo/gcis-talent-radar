"""Publish a filtered education snapshot, preserving source snapshots for audit."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from engine.education_directory import education_db_path
from engine.campus_search import excluded_program


def apply_scope(db_path=None):
    with sqlite3.connect(str(db_path or education_db_path())) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('BEGIN IMMEDIATE')
        release = conn.execute('''SELECT r.* FROM education_releases r JOIN
            education_active_release a USING(release_id) WHERE a.singleton=1''').fetchone()
        original = release['release_id']
        removed = [dict(row) for row in conn.execute(
            'SELECT department_id,institution_id,name FROM education_departments WHERE release_id=?', (original,))
            if excluded_program(row['institution_id'], row['name'])]
        if not removed:
            return {'release_id': original, 'removed_count': 0, 'removed': []}
        signature = original + json.dumps(removed, ensure_ascii=False, sort_keys=True)
        next_id = 'edu-scope-' + hashlib.sha256(signature.encode()).hexdigest()[:24]
        conn.execute('PRAGMA defer_foreign_keys=ON')
        conn.execute('INSERT INTO education_releases VALUES (?,?,?,?,?,?)',
                     (next_id, release['academic_year'], release['parser_version'] + '+program-scope/1.0',
                      datetime.now(timezone.utc).isoformat(), release['source_as_of'], release['summary_json']))
        # Clone all release-bound tables, including coordinate/contact provenance.
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            if table in {'education_releases', 'education_active_release'}:
                continue
            quoted_table = '"' + table.replace('"', '""') + '"'
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info({quoted_table})')]
            if 'release_id' not in columns:
                continue
            selections = ["?" if column == 'release_id' else '"' + column.replace('"', '""') + '"' for column in columns]
            conn.execute(f'INSERT INTO {quoted_table} SELECT {",".join(selections)} FROM {quoted_table} WHERE release_id=?',
                         (next_id, original))
        for department in removed:
            args = (next_id, department['department_id'])
            conn.execute('DELETE FROM education_department_campuses WHERE release_id=? AND department_id=?', args)
            conn.execute('DELETE FROM education_review_tasks WHERE release_id=? AND entity_id=?', args)
            conn.execute('DELETE FROM education_departments WHERE release_id=? AND department_id=?', args)
        summary = json.loads(release['summary_json'])
        summary.update(program_scope_parent=original, excluded_programs=summary.get('excluded_programs', 0)+len(removed))
        summary['program_scope_exclusions'] = removed
        for key, sql in {
            'departments': 'SELECT count(*) FROM education_departments WHERE release_id=?',
            'registry_departments': 'SELECT count(*) FROM education_departments WHERE release_id=? AND registry_listed=1',
            'supplementary_departments': 'SELECT count(*) FROM education_departments WHERE release_id=? AND registry_listed=0',
            'pending_department_campus': "SELECT count(*) FROM education_review_tasks WHERE release_id=? AND task_type='DEPARTMENT_CAMPUS'",
            'single_campus_relations': "SELECT count(*) FROM education_department_campuses WHERE release_id=? AND relation_type='SINGLE_OFFICIAL_CAMPUS'",
        }.items():
            summary[key] = conn.execute(sql, (next_id,)).fetchone()[0]
        conn.execute('UPDATE education_releases SET summary_json=? WHERE release_id=?',
                     (json.dumps(summary, ensure_ascii=False), next_id))
        if conn.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Program scope snapshot failed foreign key validation')
        conn.execute('UPDATE education_active_release SET release_id=? WHERE singleton=1', (next_id,))
        return {'release_id': next_id, 'removed_count': len(removed), 'removed': removed}


if __name__ == '__main__':
    print(json.dumps(apply_scope(), ensure_ascii=False, indent=2))
