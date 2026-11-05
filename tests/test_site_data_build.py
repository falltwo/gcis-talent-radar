"""Offline site-data generation and scheduling regressions; no network or model."""
import csv
import datetime as dt
import json
from pathlib import Path

import pytest
from etl import build_gcis_district_activity as activity, daily_refresh


def csv_file(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


@pytest.fixture
def site_inputs(tmp_path):
    processed, raw = tmp_path/'processed', tmp_path/'raw'
    csv_file(processed/'tc_factory_district_industry_annual.csv', [
        {'year':'2023','district':'太平區','industry':'機械設備業','factories':'99','factories_flag':'','employees':'999','employees_flag':''},
        {'year':'2024','district':'太平區','industry':'機械設備業','factories':'12','factories_flag':'','employees':'120','employees_flag':''},
        {'year':'2024','district':'太平區','industry':'金屬製品業','factories':'','factories_flag':'suppressed_lt4','employees':'9','employees_flag':'suppressed_lt4'},
    ])
    def job(date, district, url, family='技術／維修／操作', location=None, flag=''):
        return {'snapshot_date':date,'query_district':district,'url':url,'job_major':family,'openings':'3',
                'work_location':location or '臺中市'+district,'location_flag':flag,'job_title':'測試技術員',
                'salary_basis':'月薪','salary_min':'30000','salary_max':'35000'}
    csv_file(processed/'tc_taiwanjobs_snapshot.csv', [
        job('2026-10-02','太平區','old'),
        job('2026-11-01','太平區','same'),job('2026-11-01','太平區','same'),
        job('2026-11-01','太平區','other','工程／研發／生技'),
        job('2026-11-01','中區','wrong',location='臺中市不限',flag='taichung_unspecified'),
    ])
    csv_file(raw/'taiwanjobs/2026-11-01/411.csv',[{'OCCU_DESC（職務名稱）':'技術員','CITYNAME（工作地點）':'臺中市太平區','URL_QUERY（職缺資料URL）':u} for u in ('same','other')])
    csv_file(raw/'taiwanjobs/2026-11-01/400.csv',[{'OCCU_DESC（職務名稱）':'技術員','CITYNAME（工作地點）':'臺中市不限','URL_QUERY（職缺資料URL）':'wrong'}])
    return processed, raw


def test_stats_uses_latest_year_preserves_suppression_and_latest_deduplicated_jobs(site_inputs):
    from etl.build_district_stats import build
    processed, raw = site_inputs
    result = build(processed_dir=processed, raw_dir=raw, query_limit=2)
    assert result['factories']['year'] == 2024
    assert result['factories']['districts']['太平區'] == {'機械設備業':12,'金屬製品業':None}
    assert result['jobs']['snapshot_date'] == '2026-11-01'
    assert result['jobs']['metrics']['all_postings']['太平區'] == 2
    assert result['jobs']['metrics']['all_openings']['太平區'] == 6
    assert result['jobs']['metrics']['manufacturing_postings']['太平區'] == 1
    assert result['jobs']['metrics']['manufacturing_openings']['太平區'] == 3
    assert result['jobs']['metrics']['all_postings']['中區'] == 0
    assert result['jobs']['metrics']['all_postings']['大雅區'] is None
    assert result['jobs']['capped'] == ['太平區']
    assert '大雅區' in result['jobs']['missing_districts']
    assert result['jobs']['manufacturing_job_families'] == ['品管／製造／環衛','技術／維修／操作']
    assert result['jobs']['excluded_location_rows'] == 1


def test_activity_includes_all_twelve_months_and_reports_an_unpaired_latest_month(tmp_path,monkeypatch):
    lists = tmp_path/'lists';monkeypatch.setattr(activity,'LISTS',lists)
    for month in activity.months('2026-09',12):
        for kind in ('setup','dissolved'):
            csv_file(lists/kind/(month+'.csv'),[{'公司所在地':'臺中市太平區中山路1號'}])
    result=activity.build()
    assert result['window']==['2025-10','2026-09']
    assert result['missing_months']==[]
    assert result['districts']['太平區']['setup']==12
    csv_file(lists/'dissolved/2026-10.csv',[{'公司所在地':'臺中市太平區中山路1號'}])
    result=activity.build()
    assert result['window']==['2025-11','2026-10']
    assert result['missing_months']==['2026-10']


def test_site_refresh_build_failure_preserves_all_previous_artifacts(tmp_path,monkeypatch):
    from etl import build_site_data as module
    for name in ('district-stats.json','gcis-district-activity.json','district-talent.json'):
        (tmp_path/name).write_text('{"previous":true}')
    monkeypatch.setattr(module,'BUILDERS',{'district-stats.json':lambda:{'new':1},
        'gcis-district-activity.json':lambda:(_ for _ in ()).throw(ValueError('missing source')),
        'district-talent.json':lambda:{'new':3}})
    with pytest.raises(ValueError,match='missing source'):module.refresh(output_dir=tmp_path)
    assert all(json.loads(p.read_text())=={'previous':True} for p in tmp_path.glob('*.json'))


def test_daily_schedule_runs_site_refresh_after_upstream_rebuild(tmp_path,monkeypatch):
    monkeypatch.setattr(daily_refresh,'LOG_PATH',tmp_path/'daily.json')
    calls=[]
    for name in ('_monthly_statistics','_monthly_lists','_tax_registry','_daily_api','_business_items','_rebuild'):
        def stub(*args, _name=name, **kwargs):calls.append(_name);return {}
        monkeypatch.setattr(daily_refresh,name,stub)
    monkeypatch.setattr(daily_refresh,'_site_data',lambda:calls.append('site_data') or {'artifacts':3},raising=False)
    result=daily_refresh.run(max_calls=0,today=dt.date(2026,11,6),log=lambda _:None)
    assert calls[-2:]==['_rebuild','site_data']
    assert result['steps']['site_data']['ok'] is True


def test_talent_uses_the_same_latest_validated_snapshot_but_discloses_broader_job_families(site_inputs,monkeypatch):
    from etl import build_district_talent as module
    processed,raw=site_inputs
    csv_file(processed/'tc_udb_dept_annual.csv',[{'academic_year':'113','school':'測試大學','dept':'機械工程系','graduates':'20'}])
    csv_file(processed/'education_campus_coordinates.csv',[{'institution_name':'測試大學','district':'太平區','longitude':'120.7','latitude':'24.1'}])
    shape={'rings':[[(120,24),(121,24),(121,25),(120,25),(120,24)]],'label':[120.7,24.1]}
    monkeypatch.setattr(module,'districts_geometry',lambda:{'太平區':shape})
    result=module.build(processed_dir=processed,raw_dir=raw)
    assert result['jobs_snapshot']=='2026-11-01'
    assert result['districts']['太平區']['postings']==2
    assert result['districts']['太平區']['openings']==6
    assert result['districts']['太平區']['graduates_nearby']==20
    assert '工程／研發／生技' in result['job_families']


def test_stats_rejects_malformed_sources_instead_of_publishing_fake_zeros(site_inputs):
    from etl.build_district_stats import build
    processed,raw=site_inputs
    path=processed/'tc_factory_district_industry_annual.csv'
    path.write_text(path.read_text(encoding='utf-8-sig').replace('12,','NaN,'),encoding='utf-8-sig')
    with pytest.raises(ValueError,match='factory count'):build(processed_dir=processed,raw_dir=raw)


@pytest.mark.parametrize('content',['','<html>upstream error</html>','error\nUnavailable\n'])
def test_invalid_raw_job_audit_cannot_be_reported_as_zero(site_inputs,content):
    from etl.build_district_stats import build
    processed,raw=site_inputs
    (raw/'taiwanjobs/2026-11-01/411.csv').write_text(content)
    with pytest.raises(ValueError):build(processed_dir=processed,raw_dir=raw)


def test_invalid_gcis_header_or_addresses_do_not_publish_complete_coverage(tmp_path,monkeypatch):
    lists=tmp_path/'lists';monkeypatch.setattr(activity,'LISTS',lists)
    for kind in ('setup','dissolved'):
        csv_file(lists/kind/'2026-09.csv',[{'error':'Unavailable'}])
    with pytest.raises(ValueError):activity.build()
    for kind in ('setup','dissolved'):
        csv_file(lists/kind/'2026-09.csv',[{'公司所在地':'上游維護中'}])
    with pytest.raises(ValueError):activity.build()


def test_publish_failure_restores_exact_previous_bytes(tmp_path,monkeypatch):
    from etl import build_site_data as module
    original=b'{"previous":true}\n'
    names=['district-stats.json','gcis-district-activity.json','district-talent.json']
    for name in names:(tmp_path/name).write_bytes(original)
    monkeypatch.setattr(module,'BUILDERS',{name:lambda:{'new':1} for name in names})
    replace=module.os.replace;calls=[]
    def fail_second(src,dst):
        calls.append(dst)
        if len(calls)==2:raise OSError('disk failure')
        return replace(src,dst)
    monkeypatch.setattr(module.os,'replace',fail_second)
    with pytest.raises(OSError,match='disk failure'):module.refresh(output_dir=tmp_path)
    assert all((tmp_path/name).read_bytes()==original for name in names)


def test_raw_audit_must_cover_unique_processed_records(site_inputs):
    from etl.build_district_stats import build
    processed,raw=site_inputs
    path=raw/'taiwanjobs/2026-11-01/411.csv'
    with path.open(encoding='utf-8-sig') as handle:rows=list(csv.DictReader(handle))
    csv_file(path,rows[:1])
    with pytest.raises(ValueError,match='processed rows exceed raw'):build(processed_dir=processed,raw_dir=raw)


def test_unknown_or_capped_talent_district_is_not_published_as_zero(site_inputs,monkeypatch):
    from etl import build_district_talent as module
    processed,raw=site_inputs
    csv_file(processed/'tc_udb_dept_annual.csv',[{'academic_year':'113','school':'測試大學','dept':'機械工程系','graduates':'20'}])
    csv_file(processed/'education_campus_coordinates.csv',[{'institution_name':'測試大學','district':'太平區','longitude':'120.7','latitude':'24.1'}])
    shape={'rings':[[(120,24),(121,24),(121,25),(120,25),(120,24)]],'label':[120.7,24.1]}
    monkeypatch.setattr(module,'districts_geometry',lambda:{'大雅區':shape})
    with pytest.raises(ValueError,match='audited, uncapped'):module.build(processed_dir=processed,raw_dir=raw)
    monkeypatch.setattr(module,'districts_geometry',lambda:{'太平區':shape})
    path=raw/'taiwanjobs/2026-11-01/411.csv'
    with path.open(encoding='utf-8-sig') as handle:rows=list(csv.DictReader(handle))
    csv_file(path,rows*500)
    with pytest.raises(ValueError,match='audited, uncapped'):module.build(processed_dir=processed,raw_dir=raw)


def test_refresh_preserves_employees_and_suppression_for_rankings(site_inputs,tmp_path,monkeypatch):
    from etl import build_site_data as module
    from etl.build_district_stats import build
    processed,raw=site_inputs
    monkeypatch.setitem(module.BUILDERS,'district-stats.json',lambda:build(processed_dir=processed,raw_dir=raw))
    monkeypatch.setitem(module.BUILDERS,'gcis-district-activity.json',lambda:{})
    monkeypatch.setitem(module.BUILDERS,'district-talent.json',lambda:{})
    target=tmp_path/'published'
    module.refresh(output_dir=target)
    data=json.loads((target/'district-stats.json').read_text())
    assert data['factories']['employees']['太平區']=={'機械設備業':120,'金屬製品業':None}
    assert data['factories']['employees']['大雅區']=={'機械設備業':None,'金屬製品業':None}
    # A second scheduled rebuild must not drop the field again.
    module.refresh(output_dir=target)
    assert json.loads((target/'district-stats.json').read_text())==data


def test_employee_unknowns_and_invalid_counts_are_not_zeroed(site_inputs):
    from etl.build_district_stats import build
    processed,raw=site_inputs
    path=processed/'tc_factory_district_industry_annual.csv'
    with path.open(encoding='utf-8-sig') as handle:rows=list(csv.DictReader(handle))
    rows[1]['employees']=''
    csv_file(path,rows)
    assert build(processed_dir=processed,raw_dir=raw)['factories']['employees']['太平區']['機械設備業'] is None
    rows[1]['employees']='NaN';csv_file(path,rows)
    with pytest.raises(ValueError,match='employee count'):build(processed_dir=processed,raw_dir=raw)
