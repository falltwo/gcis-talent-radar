from datetime import date
from types import SimpleNamespace
import requests
import recruitment.taiwan_salary as salary


def row(**kwargs):
    return {'occupation_title':'前端工程師','work_location':'臺中市大雅區','salary_type':'月薪','salary_lower':40000,'salary_upper':60000,'source_url':'https://job.taiwanjobs.gov.tw/1','application_deadline':'20261231',**kwargs}


def summary(rows):
    return salary.summarize('前端工程師','大雅區',rows,snapshot='2026-11-05',fetched_at='2026-11-05T00:00:00Z',mode='live',today=date(2026,11,5))


def test_salary_reference_excludes_other_roles_places_hourly_expired_and_invalid_ranges():
    result=summary([row(),row(),row(source_url='2',salary_lower=50000,salary_upper=70000),row(source_url='3',occupation_title='後端工程師'),row(source_url='4',salary_type='時薪'),row(source_url='5',work_location='臺中市西屯區'),row(source_url='6',application_deadline='20251001'),row(source_url='7',salary_lower=80000,salary_upper=60000),row(source_url='8',salary_lower=None)])
    assert result['sample_count']==2
    assert (result['salary_min'],result['salary_max'])==(45000,65000)
    assert result['statistic']=='posted_range_endpoint_medians'
    assert '不是平均實領薪資' in result['notice']


def test_region_does_not_silently_change_city(monkeypatch):
    assert salary.district_in('臺北市大安區') is None
    assert salary.district_in('臺中市大安區')=='大安區'
    monkeypatch.setattr(salary,'_reference_for',lambda role,area:{'status':'available','region':area,'sample_count':3})
    result=salary.get_reference('前端工程師','臺北市大安區')
    assert result['requested_region']=='臺北市'
    assert result['status']=='no_samples'
    assert result['searched_regions']==[]


def test_live_source_falls_back_with_original_snapshot_date(monkeypatch):
    snapshot_date=date(2025,12,15).isoformat()
    def fail(*a):raise requests.Timeout()
    monkeypatch.setattr(salary,'fetch_rows',fail)
    monkeypatch.setattr(salary,'snapshot_rows',lambda *a:([row()], snapshot_date,snapshot_date+'T12:00:00Z','snapshot',True))
    result=salary.get_reference('前端工程師','大雅區')
    assert result['mode']=='snapshot' and result['snapshot_date']==snapshot_date
    assert result['cap_reached'] is True


def test_empty_source_never_invents_amounts():
    result=summary([])
    assert result['sample_count']==0
    assert result['salary_min'] is result['salary_max'] is None


def test_official_csv_parses_named_columns_and_caches(monkeypatch):
    salary._cache.clear();calls=[]
    def fetch(*a,**kw):
        calls.append(kw['params'])
        content='OCCU_DESC（職務名稱）,CITYNAME（工作地點）,SALARYCD（核薪方式）,NT_L（下限）,NT_U（上限）,URL_QUERY（網址）\r\n前端工程師,臺中市大雅區,月薪,40000,60000,https://job.taiwanjobs.gov.tw/1\r\n'
        return SimpleNamespace(content=content.encode('utf-8-sig'),raise_for_status=lambda:None)
    monkeypatch.setattr(salary.requests,'get',fetch)
    first=salary.fetch_rows('大雅區');second=salary.fetch_rows('大雅區')
    assert first==second and len(calls)==1 and calls[0]['zipno']=='428'
    assert first[0][0]['salary_lower']=='40000'
    salary._cache.clear()


def test_salary_starts_with_taichung_city_and_never_queries_districts(monkeypatch):
    calls=[]
    def reference(role,area):
        calls.append(area)
        return {'status':'available','region':('臺中市'+area if area in salary.POSTAL else area),'sample_count':4 if area=='新竹市' else 0}
    monkeypatch.setattr(salary,'_reference_for',reference)
    result=salary.get_reference('前端工程師','新社區')
    assert result['region']=='新竹市' and result['expanded'] is True
    assert result['requested_region']=='臺中市'
    assert calls==['臺中市','新竹市']


def test_sufficient_local_samples_stop_expansion(monkeypatch):
    calls=[]
    def reference(role,area):
        calls.append(area)
        return {'status':'available','region':'臺中市','sample_count':4}
    monkeypatch.setattr(salary,'_reference_for',reference)
    result=salary.get_reference('作業員','大雅區')
    assert calls==['臺中市'] and not result['expanded']


def test_empty_regions_continue_to_source_backed_search(monkeypatch):
    monkeypatch.setattr(salary,'get_reference',lambda *a:{'status':'no_samples'})
    assert salary.salary_answer('新社區前端工程師薪資') is None
