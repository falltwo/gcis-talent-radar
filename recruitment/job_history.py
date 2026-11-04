"""Bounded local history of public occupational research, never HR/company input."""
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

TTL_SECONDS = 30 * 86400
MAX_ITEMS = 200
CONTENT_FIELDS = ('description', 'required_skills', 'trainable_skills', 'review_notes')


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


class JobHistory:
    def __init__(self):
        default = Path(__file__).resolve().parents[1] / 'data' / 'recruitment-history' / 'templates.sqlite'
        self.path = Path(os.environ.get('RECRUITMENT_TEMPLATE_HISTORY_DB', str(default)))

    @staticmethod
    def valid(payload):
        content = payload.get('content', {})
        sources = payload.get('sources', [])
        return (isinstance(content.get('description'), str) and 10 <= len(content['description']) <= 1200
                and all(isinstance(content.get(k), list) and all(isinstance(v, str) and len(v) <= 250 for v in content[k]) for k in CONTENT_FIELDS[1:])
                and all(len(content[k]) <= 8 and all(0 < len(v.strip()) <= 80 for v in content[k]) for k in CONTENT_FIELDS[1:3])
                and isinstance(sources, list) and 1 <= len(sources) <= 5
                and all(isinstance(s, dict) and isinstance(s.get('url'), str) and s['url'].startswith('https://') for s in sources))

    def items(self):
        if not self.path.is_file():
            return []
        try:
            with closing(sqlite3.connect(self.path, timeout=2)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute('SELECT * FROM job_template_history WHERE expires_at > ? ORDER BY saved_at DESC, rowid DESC LIMIT ?', (time.time(), MAX_ITEMS)).fetchall()
            result = []
            for row in rows:
                try:
                    payload = json.loads(row['payload'])
                    if self.valid(payload):
                        result.append({**payload, 'key': row['role_key'], 'role': row['role'],
                                       'saved_at': iso(row['saved_at']), 'expires_at': iso(row['expires_at'])})
                except (ValueError, TypeError, AttributeError):
                    continue
            return result
        except sqlite3.Error as exc:
            raise RuntimeError('歷史範本暫時無法讀取，請稍後再試。') from exc

    def get(self, key):
        return next((item for item in self.items() if item['key'] == key), None)

    def save(self, key, role, generated, sources):
        # Never serialize arbitrary generated metadata or the HR request body.
        payload = {'content': {k: generated[k] for k in CONTENT_FIELDS},
                   'sources': [{k: s.get(k) for k in ('title', 'url', 'retrieved_at')} for s in sources]}
        if not self.valid(payload):
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=2)) as conn, conn:
                conn.execute('CREATE TABLE IF NOT EXISTS job_template_history (role_key TEXT PRIMARY KEY, role TEXT NOT NULL, payload TEXT NOT NULL, saved_at REAL NOT NULL, expires_at REAL NOT NULL)')
                now = time.time()
                conn.execute('DELETE FROM job_template_history WHERE expires_at <= ?', (now,))
                conn.execute('INSERT INTO job_template_history VALUES(?,?,?,?,?) ON CONFLICT(role_key) DO UPDATE SET role=excluded.role,payload=excluded.payload,saved_at=excluded.saved_at,expires_at=excluded.expires_at',
                             (key, role, json.dumps(payload, ensure_ascii=False), now, now + TTL_SECONDS))
                conn.execute('DELETE FROM job_template_history WHERE role_key NOT IN (SELECT role_key FROM job_template_history ORDER BY saved_at DESC, rowid DESC LIMIT ?)', (MAX_ITEMS,))
            return True
        except (OSError, sqlite3.Error):
            return False
