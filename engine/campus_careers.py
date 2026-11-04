"""Reverse lookup from public career titles to departments in the directory."""
import json
import re
from functools import lru_cache
from itertools import chain

from config import BASE_DIR
from engine.campus_search import normalize


COLLEGO = 'https://collego.edu.tw/Highschool/'
CAREER_FILE = BASE_DIR / 'data/processed/campus_careers.json'
SUPPLEMENT_FILE = CAREER_FILE.with_name('campus_career_supplements.json')
ROLE_NAMES = (
    ('軟體工程師', '軟體設計工程師', '程式設計師', 'software engineer', 'software developer'),
    ('資安工程師', '資訊安全工程師', '網路安全工程師'),
    ('AI工程師', '人工智慧工程師'),
    ('資料分析師', '數據分析師', 'data analyst'),
    ('機構工程師', '機構設計工程師'),
    ('品管人員', '品保人員', '品管檢驗人員'),
    ('品管工程師', '品保工程師', '品質管理工程師', '品管／品保工程師'),
    ('CNC', 'CNC技術員', 'CNC操作員', 'CNC機台操作人員', 'CNC車床人員', 'CNC銑床人員', '自動化機械加工技術人員'),
    ('稅務專員', '稅務人員', '稅務會計', '報稅人員'),
    ('企業法務', '法務專員', '法務人員'),
    ('智財專員', '專利人員', '商標╱專利人員', '商標／專利人員'),
)


@lru_cache(maxsize=1)
def career_index():
    if not CAREER_FILE.is_file():
        return None, {}, {}
    snapshot = json.loads(CAREER_FILE.read_text(encoding='utf-8'))
    profiles = {}
    for dept_id, profile in snapshot['departments'].items():
        profiles[dept_id] = {}
        for tier, page in (('direct', 'DepartmentIntro?dept_id='), ('related', 'MajorIntro?current_major_id=')):
            profiles[dept_id][tier] = [
                {'title': re.sub(r'^\d+\s*[|｜]\s*', '', title), 'source_url': COLLEGO + page + source_id}
                for source_id in profile[tier] for title in snapshot[tier][source_id]
            ]
    if SUPPLEMENT_FILE.is_file():
        for dept_id, entry in json.loads(SUPPLEMENT_FILE.read_text(encoding='utf-8')).items():
            profiles.setdefault(dept_id, {}).setdefault('direct', []).extend(
                {'title': title, 'source_url': entry['source_url']} for title in entry['roles']
            )
    titles = {normalize(job['title']): job['title'] for profile in profiles.values()
              for jobs in profile.values() for job in jobs}
    return snapshot['version'], profiles, titles


def _database_careers(conn, release_id):
    if conn is None or not conn.execute(
        "SELECT 1 FROM sqlite_schema WHERE name='education_career_supplements' AND type='table'"
    ).fetchone():
        return {}, {}
    profiles = {}
    for dept_id, tier, title, url in conn.execute('''
        SELECT s.department_id, s.tier, s.title, s.source_url
        FROM education_career_supplements s JOIN education_departments d USING (department_id)
        WHERE d.release_id=? ORDER BY s.department_id, s.title, s.source_url
    ''', (release_id,)):
        job = {'title': title, 'source_url': url}
        if tier == 'related':
            job['basis'] = 'TRAINING'
        profiles.setdefault(dept_id, {}).setdefault(tier, []).append(job)
    return profiles, dict(conn.execute('SELECT alias, title FROM education_career_aliases'))


def search_careers(query, *, conn=None, release_id=None):
    """Return the roles recognized in a keyword and their department evidence."""
    keyword = normalize(query)
    if len(keyword) < 2:
        return {}, {}
    version, profiles, titles = career_index()
    additions, database_aliases = _database_careers(conn, release_id)
    if additions:
        titles = {**titles, **{normalize(job['title']): job['title'] for profile in additions.values()
                              for jobs in profile.values() for job in jobs}}
        version = 'campus-careers/1.1'
    aliases = {normalize(title) for group in ROLE_NAMES if keyword in map(normalize, group) for title in group}
    if keyword in database_aliases:
        aliases.add(normalize(database_aliases[keyword]))
    terms = (aliases | {keyword}) & titles.keys()
    if not terms:
        terms = {key for key in titles if keyword in key}
    if not terms:
        return {}, {}

    matches = {}
    for dept_id in dict.fromkeys(chain(profiles, additions)):
        evidence = {}
        for tier in ('direct', 'related'):
            jobs = {}
            for job in chain(additions.get(dept_id, {}).get(tier, []), profiles.get(dept_id, {}).get(tier, [])):
                key = normalize(job['title'])
                if key in terms:
                    jobs.setdefault(key, job)
            if jobs:
                evidence[tier] = list(jobs.values())
        if evidence:
            matches[dept_id] = evidence
    return {'version': version, 'roles': sorted(titles[key] for key in terms)}, matches
