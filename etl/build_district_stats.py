"""Reproduce district-stats.json from the latest local factory/job snapshots.

Manufacturing-related map jobs = 技術／維修／操作 OR 品管／製造／環衛.
This is a job-family proxy, not an employer industry label. Suppressed/missing
factory observations remain null; unaudited job districts remain null.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from etl.site_data_sources import MAP_JOB_FAMILIES, csv_rows, latest_jobs, nonnegative_number
from etl.sources.common import TAICHUNG_DISTRICTS

OUT = ROOT/'ui/static/district-stats.json'


def build(processed_dir=None, raw_dir=None, query_limit=1000):
    processed_dir = Path(processed_dir or ROOT/'data/processed')
    rows = csv_rows(processed_dir/'tc_factory_district_industry_annual.csv',
                    ['year','district','industry','factories','factories_flag','employees','employees_flag'])
    if not rows:
        raise ValueError('Empty factory statistics')
    year = max(nonnegative_number(row['year'],'factory year',integer=True) for row in rows)
    rows = [row for row in rows if int(row['year']) == year]
    industries = sorted({row['industry'] for row in rows})
    factories = {district:dict.fromkeys(industries) for district in TAICHUNG_DISTRICTS}
    employees = {district:dict.fromkeys(industries) for district in TAICHUNG_DISTRICTS}
    seen = set()
    for row in rows:
        if row['district'] not in factories:
            continue
        key = (row['district'], row['industry'])
        if key in seen:
            raise ValueError(f'Duplicate factory observation: {key}')
        seen.add(key)
        factories[key[0]][key[1]] = (None if row['factories_flag'] or not row['factories'].strip()
                                    else nonnegative_number(row['factories'],'factory count',integer=True))
        employees[key[0]][key[1]] = (None if row['employees_flag'] or not row['employees'].strip()
                                    else nonnegative_number(row['employees'],'employee count',integer=True))
    jobs = latest_jobs(processed_dir,raw_dir,query_limit)
    metrics = {name:{d:(None if d in jobs['missing_districts'] else 0) for d in TAICHUNG_DISTRICTS}
               for name in ('all_postings','all_openings','manufacturing_postings','manufacturing_openings')}
    for row in jobs['rows']:
        district = row['query_district']
        metrics['all_postings'][district] += 1
        metrics['all_openings'][district] += row['openings']
        if row['job_major'] in MAP_JOB_FAMILIES:
            metrics['manufacturing_postings'][district] += 1
            metrics['manufacturing_openings'][district] += row['openings']
    return {'factories':{'year':year,'source':'經濟部工廠校正統計調查（EE520）',
                'source_url':'https://service.moea.gov.tw/EE520/investigate/InvestigateG.aspx',
                'null_rule':'原始空白、保密或無數值保留 null，家數與員工數皆不當作 0', 'districts':factories, 'employees':employees},
            'jobs':{key:value for key,value in jobs.items() if key != 'rows'} | {
                'source':'台灣就業通職缺清單','source_url':'https://data.gov.tw/dataset/44062',
                'manufacturing_job_families':sorted(MAP_JOB_FAMILIES),
                'manufacturing_rule':'職務大類名稱擇一符合；非雇主行業分類，刊登筆數不等於缺工人數',
                'location_rule':'工作地點明確位於查詢區，排除 location_flag，最新快照依職缺 URL 去重',
                'metrics':metrics}}


if __name__ == '__main__':
    from etl.build_site_data import write_artifact
    data=build();write_artifact(OUT,data)
    print(json.dumps({'factory_year':data['factories']['year'],'jobs_snapshot':data['jobs']['snapshot_date']},ensure_ascii=False))
