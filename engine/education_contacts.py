"""Published institution switchboards with traceable official source metadata."""
import re


def read_institution_contacts(conn, release_id):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='education_institution_contacts'").fetchone():
        return {}
    result = {}
    for record in conn.execute('SELECT * FROM education_institution_contacts WHERE release_id=?', (release_id,)):
        row = dict(record)
        if not re.fullmatch(r'\+886[2-8]\d{7,8}', row['phone_e164']):
            continue
        result[row['institution_id']] = {
            'status': 'AVAILABLE', 'label': '學校總機', 'kind': row['contact_kind'],
            'display': row['phone_display'], 'tel_uri': 'tel:' + row['phone_e164'],
            'source_url': row['source_url'], 'source_sha256': row['source_sha256'],
            'source_period': row['source_period'], 'checked_at': row['checked_at'],
        }
    return result


def missing_phone():
    return {'status': 'UNAVAILABLE', 'label': '學校總機', 'display': None,
            'tel_uri': None, 'source_url': None, 'checked_at': None}
