"""Refresh campus career titles from the public ColleGo school and field pages."""
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import requests
from bs4 import BeautifulSoup

from config import BASE_DIR
from engine.campus_search import normalize
from engine.education_directory import _release, directory_connection


COLLEGO = 'https://collego.edu.tw/Highschool/'
OUTPUT = BASE_DIR / 'data/processed/campus_careers.json'


def page(path):
    response = requests.get(COLLEGO + path, timeout=25)
    response.raise_for_status()
    return BeautifulSoup(response.content, 'html.parser')


def link_id(anchor, field):
    values = parse_qs(urlsplit(anchor['href']).query).get(field, [])
    return next((value for value in values if value.isascii() and value.isdecimal()), None)


def major(major_id):
    soup = page(f'MajorIntro?current_major_id={major_id}')
    jobs = [node.get_text(' ', strip=True) for node in soup.select('#tab6default li[data-slide-to] p')]
    schools = []
    for anchor in soup.select('a[href*="DepartmentIntro?dept_id="]'):
        row = anchor.find_parent('tr')
        if row and row.find('td') and (dept_id := link_id(anchor, 'dept_id')):
            key = (normalize(row.find('td').get_text()), normalize(anchor.get_text()))
            schools.append((key, dept_id))
    return major_id, list(dict.fromkeys(jobs)), schools


def department(dept_id):
    soup = page(f'DepartmentIntro?dept_id={dept_id}')
    heading = soup.select_one('#tab3default h3')
    jobs = []
    if heading and heading.get_text(strip=True) == '適合從事工作':
        jobs = [node.get_text(' ', strip=True) for node in heading.parent.select('li > h4')]
    return dept_id, list(dict.fromkeys(jobs))


def main():
    with directory_connection() as conn:
        release_id = _release(conn)['release_id']
        directory = {}
        for row in conn.execute('''
            SELECT i.name AS school, d.name, d.department_id
            FROM education_departments d JOIN education_institutions i USING (release_id, institution_id)
            WHERE d.release_id=? AND i.in_taichung_scope=1
        ''', (release_id,)):
            directory.setdefault((normalize(row['school']), normalize(row['name'])), []).append(row['department_id'])

    index = page('MajorList')
    major_ids = sorted({key for a in index.select('a[href*="MajorIntro?"]')
                        if (key := link_id(a, 'current_major_id'))}, key=int)
    if not major_ids:
        raise RuntimeError('ColleGo major index returned no entries')
    majors, memberships = {}, {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for major_id, jobs, schools in pool.map(major, major_ids):
            for key, source_id in schools:
                for dept_id in directory.get(key, []):
                    memberships.setdefault(dept_id, {}).setdefault(source_id, set()).add(major_id)
            if jobs:
                majors[major_id] = jobs
        print(f'Matched {len(memberships)} departments from {len(major_ids)} major pages', flush=True)
        source_ids = sorted({key for dept in memberships.values() for key in dept})
        direct = dict(pool.map(department, source_ids))

    departments = {}
    used_majors = set()
    for dept_id, pages in sorted(memberships.items()):
        direct_ids = [key for key in sorted(pages) if direct[key]]
        related_ids = sorted({key for group in pages.values() for key in group if key in majors}, key=int)
        used_majors.update(related_ids)
        if direct_ids or related_ids:
            departments[dept_id] = {'direct': direct_ids, 'related': related_ids}
    if not departments or not any(d['direct'] for d in departments.values()):
        raise RuntimeError('No campus career profiles found')
    snapshot = {
        'version': 'campus-careers/1.0',
        'source': COLLEGO + 'MajorList',
        'departments': departments,
        'direct': {key: jobs for key, jobs in sorted(direct.items()) if jobs},
        'related': {key: majors[key] for key in sorted(used_majors, key=int)},
    }
    temp = OUTPUT.with_suffix('.tmp')
    temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(OUTPUT)
    print(f'Wrote {len(departments)} profiles to {OUTPUT.name}')


if __name__ == '__main__':
    main()
