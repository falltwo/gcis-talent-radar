"""Import verified switchboards from the MOE roster without changing other data."""
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
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import BASE_DIR
from engine.education_directory import education_db_path

SOURCE_URL = 'https://udb.moe.edu.tw/ulist/Resource/download/ulistaddress?extension=csv'


def parse_roster(raw):
    lines = raw.decode('utf-8-sig').splitlines()
    start = next((i for i, line in enumerate(lines) if '學校代碼' in line and '學校總機' in line), None)
    if start is None:
        raise ValueError('名錄缺少學校代碼或學校總機欄位')
    return list(csv.DictReader(io.StringIO('\n'.join(lines[start:]))))


def normalize_phone(value):
    display = unicodedata.normalize('NFKC', value or '').strip()
    digits = re.sub(r'[\s()－—-]', '', display)
    if not re.fullmatch(r'0[2-8]\d{7,8}', digits):
        raise ValueError('學校總機不是可確認的臺灣市話格式')
    return display, '+886' + digits[1:]


def fetch_contacts_bundle():
    from etl.load_official_labor_market import government_session
    with government_session() as session:
        response = session.get(SOURCE_URL, timeout=45)
        response.raise_for_status()
    raw = response.content
    parse_roster(raw)  # Reject an error page before publishing a source bundle.
    now = datetime.now(ZoneInfo('Asia/Taipei'))
    folder = BASE_DIR / 'data/raw/education/contacts' / now.strftime('%Y%m%dT%H%M%S%f')
    folder.mkdir(parents=True)
    raw_path = folder / 'schools.csv'
    raw_path.write_bytes(raw)
    lines = raw.decode('utf-8-sig').splitlines()
    start = next(i for i, line in enumerate(lines) if '學校代碼' in line and '學校總機' in line)
    manifest = {'source_url': SOURCE_URL, 'final_url': response.url,
                'checked_at': now.isoformat(timespec='seconds'), 'sha256': hashlib.sha256(raw).hexdigest(),
                'raw_path': raw_path.relative_to(BASE_DIR).as_posix(), 'source_header': lines[:start]}
    (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return folder


def _name(value):
    return ''.join(unicodedata.normalize('NFKC', value).split()).replace('台', '臺')


def import_contacts(bundle, db_path=None):
    bundle = Path(bundle)
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    raw_path = (BASE_DIR / manifest['raw_path']).resolve()
    if not raw_path.is_relative_to(BASE_DIR) or manifest['source_url'] != SOURCE_URL:
        raise ValueError('電話來源不在預期的官方資料範圍')
    raw = raw_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['sha256']:
        raise ValueError('電話原始來源 checksum 不符')
    rows = parse_roster(raw)
    path = Path(db_path or education_db_path()).resolve()
    # mode=rw rejects a missing database instead of creating an empty one.
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        release = conn.execute('SELECT release_id FROM education_active_release WHERE singleton=1').fetchone()
        if not release:
            raise ValueError('尚未發布教育名冊')
        rid = release[0]
        schools = conn.execute('SELECT institution_id,name FROM education_institutions WHERE release_id=? AND in_taichung_scope=1', (rid,)).fetchall()
        if not schools:
            raise ValueError('名冊沒有臺中學校')
        records = []
        for sid, name in schools:
            matches = [row for row in rows if row['學校代碼'].strip().zfill(4) == sid]
            if len(matches) != 1 or _name(matches[0]['學校名稱']) != _name(name):
                raise ValueError('學校代碼與名稱無法唯一核對：' + sid)
            display, e164 = normalize_phone(matches[0]['學校總機'])
            records.append((rid, sid, 'INSTITUTION_SWITCHBOARD', display, e164, SOURCE_URL,
                            manifest['sha256'], raw_path.relative_to(BASE_DIR).as_posix(),
                            manifest['source_header'][0].split(',')[0], manifest['checked_at']))
        backup_dir = BASE_DIR / 'tmp/education-contact-backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / (datetime.now(ZoneInfo('Asia/Taipei')).strftime('%Y%m%dT%H%M%S%f') + '.sqlite3')
        with closing(sqlite3.connect(backup_path)) as target:
            conn.backup(target)
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute((BASE_DIR / 'database/education_contacts_schema.sql').read_text(encoding='utf-8'))
            conn.executemany('''INSERT INTO education_institution_contacts VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(release_id,institution_id,contact_kind) DO UPDATE SET
                phone_display=excluded.phone_display,phone_e164=excluded.phone_e164,source_url=excluded.source_url,
                source_sha256=excluded.source_sha256,raw_path=excluded.raw_path,
                source_period=excluded.source_period,checked_at=excluded.checked_at''', records)
            if conn.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('電話資料外鍵驗證失敗')
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return {'release_id': rid, 'institutions': len(schools), 'contacts_imported': len(records),
                'source_url': SOURCE_URL, 'source_sha256': manifest['sha256'],
                'checked_at': manifest['checked_at'], 'backup_path': str(backup_path)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--bundle', type=Path)
    source.add_argument('--download', action='store_true')
    parser.add_argument('--db', type=Path)
    args = parser.parse_args()
    print(json.dumps(import_contacts(fetch_contacts_bundle() if args.download else args.bundle, args.db), ensure_ascii=False, indent=2))
