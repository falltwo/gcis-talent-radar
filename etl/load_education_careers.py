"""Install reviewed campus career additions into an existing education database."""
import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from config import BASE_DIR
from engine.campus_search import normalize
from engine.education_directory import education_db_path


SCHEMA = BASE_DIR / 'database/education_careers_schema.sql'
SEED = BASE_DIR / 'data/processed/campus_career_additions.json'


def import_careers(db_path=None):
    path = Path(db_path or education_db_path()).resolve()
    data = json.loads(SEED.read_text(encoding='utf-8'))
    records = []
    for entry in data['evidence']:
        source = urlsplit(entry['source_url'])
        if source.scheme != 'https' or not source.hostname:
            raise ValueError('職涯來源需使用 HTTPS 網址')
        for tier in ('direct', 'related'):
            records.extend((entry['department_id'], title, tier, entry['source_url'])
                           for title in entry.get(tier, []))
    aliases = [(normalize(alias), title) for alias, title in data['aliases'].items()]

    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as conn:
        backup_dir = BASE_DIR / 'data/backups/education'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / ('before-careers-' + datetime.now().strftime('%Y%m%dT%H%M%S%f') + '.db')
        with closing(sqlite3.connect(backup_path)) as backup:
            conn.backup(backup)

        with conn:
            conn.executescript('BEGIN IMMEDIATE;\n' + SCHEMA.read_text(encoding='utf-8'))
            department_ids = {row[0] for row in conn.execute('''
                SELECT department_id FROM education_departments
                JOIN education_active_release USING (release_id)
                WHERE singleton=1
            ''')}
            missing = {record[0] for record in records} - department_ids
            if missing:
                raise ValueError(f'現行名冊缺少職涯資料所對應的系所：{sorted(missing)}')
            conn.executemany('''
                INSERT INTO education_career_supplements (department_id, title, tier, source_url)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(department_id, title, source_url) DO UPDATE SET tier=excluded.tier
            ''', records)
            conn.executemany('''
                INSERT INTO education_career_aliases (alias, title) VALUES (?, ?)
                ON CONFLICT(alias) DO UPDATE SET title=excluded.title
            ''', aliases)
    return {'career_records': len(records), 'aliases': len(aliases), 'backup_path': str(backup_path)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path)
    print(json.dumps(import_careers(parser.parse_args().db), ensure_ascii=False))
