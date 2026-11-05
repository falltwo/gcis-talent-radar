"""TaiwanJobs posted monthly salary references; never a market earnings average."""
import csv
import io
import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
import requests
from config import DB_PATH
from recruitment.job_research import find_template, TEMPLATES, normalize_role

API='https://free.taiwanjobs.gov.tw/webservice_taipei/Webservice.ashx'
SOURCE={'title':'勞動部台灣就業通：職缺刊登薪資（資料集44062）','url':'https://data.gov.tw/dataset/44062'}
SURVEY={'title':'勞動部職類別薪資調查：實際受僱員工薪資統計','url':'https://pswst.mol.gov.tw/psdn/Default.aspx'}
# The same postal scope used by the existing official labor-market loader.
POSTAL=dict(zip(['中區','東區','南區','西區','北區','北屯區','西屯區','南屯區','太平區','大里區','霧峰區','烏日區','豐原區','后里區','石岡區','東勢區','和平區','新社區','潭子區','大雅區','神岡區','大肚區','沙鹿區','龍井區','梧棲區','清水區','大甲區','外埔區','大安區'],['400','401','402','403','404','406','407','408','411','412','413','414','420','421','422','423','424','426','427','428','429','432','433','434','435','436','437','438','439']))
# Broader queries remain labelled with the actual queried geography.
CITY_QUERIES={'臺中市':{'city':'13'},'臺北市內湖區':{'zipno':'114'},'臺北市南港區':{'zipno':'115'},'新竹市':{'zipno':'300'},'桃園市中壢區':{'zipno':'320'},'高雄市前鎮區':{'zipno':'806'}}
NEARBY={'新社區':['豐原區','潭子區'],'大雅區':['西屯區','北屯區'],'潭子區':['北屯區','豐原區'],'神岡區':['大雅區','豐原區'],'西屯區':['北屯區','南屯區'],'北屯區':['西屯區','潭子區']}
_cache={}
_lock=threading.Lock()


def query_role(text):
    normalized=normalize_role(text)
    matches=[(len(normalize_role(alias)),name) for name,t in TEMPLATES.items() for alias in t['aliases'] if normalize_role(alias) in normalized]
    matches.extend((len(normalize_role(a)),name) for name,aliases in {'全端工程師':['全端工程師','全端開發工程師','full stack engineer','fullstack developer']}.items() for a in aliases if normalize_role(a) in normalized)
    return max(matches,default=(0,None))[1]


def outside_scope(text):
    return bool(re.search(r"(?:臺北|台北|新北|桃園|臺南|台南|高雄|新竹|嘉義|基隆|宜蘭|苗栗|彰化|南投|雲林|屏東|花蓮|臺東|台東|澎湖|金門|連江)[市縣]",text))


def district_in(text):
    if outside_scope(text):return None
    # Prefer long district names: 大里區 must not become another area.
    return next((d for d in sorted(POSTAL,key=len,reverse=True) if d in text),None)


def deadline_valid(value,today):
    text=str(value or '').strip()
    if not text or text in {'額滿為止','長期徵才'}:return True
    digits=re.sub(r'[^0-9]','',text)
    try:
        if len(digits)==7:digits=str(int(digits[:3])+1911)+digits[3:]
        return len(digits)==8 and date.fromisoformat(f'{digits[:4]}-{digits[4:6]}-{digits[6:]}')>=today
    except ValueError:return False


def summarize(role,district,rows,*,snapshot,fetched_at,mode,cap_reached=False,today=None):
    today=today or date.today()
    found=find_template(role)
    aliases=found[1]['aliases'] if found else [role]
    aliases=[normalize_role(a) for a in aliases]
    samples={}
    for row in rows:
        title=normalize_role(str(row.get('occupation_title','')))
        if not any(a and a in title for a in aliases):continue
        place=str(row.get('work_location','')).replace('臺','台')
        expected=('台中市'+district) if district in POSTAL else district.replace('臺','台')
        if expected not in place:continue
        if not deadline_valid(row.get('application_deadline'),today):continue
        if str(row.get('salary_type','')).strip()!='月薪':continue
        try:lo=float(row['salary_lower']);hi=float(row['salary_upper'])
        except (TypeError,ValueError,KeyError):continue
        if not (0<lo<=hi<=10000000):continue
        identifier=row.get('source_url') or row.get('record_id')
        if not identifier:continue
        samples[identifier]={'title':row['occupation_title'],'lower':int(lo),'upper':int(hi),'updated_date':row.get('updated_date','')}
    values=list(samples.values())
    return {'role':role,'region':('臺中市'+district if district in POSTAL else district),'currency':'TWD','salary_type':'monthly',
        'statistic':'posted_range_endpoint_medians','sample_count':len(values),
        'salary_min':int(median([s['lower'] for s in values])) if values else None,
        'salary_max':int(median([s['upper'] for s in values])) if values else None,
        'snapshot_date':snapshot,'fetched_at':fetched_at,'mode':mode,'cap_reached':cap_reached,
        'sources':[SOURCE,SURVEY], 'examples':values[:3],
        'notice':'數字為符合職稱及地區的職缺開價下限、上限各自中位數；不是平均實領薪資，不代表企業核定薪資。只涵蓋台灣就業通刊登職缺。'}


def fetch_rows(district):
    with _lock:
        cached=_cache.get(district)
        if cached and time.monotonic()-cached[0]<900:return cached[1]
    params={'count':'1000','T':'CSV',**({'city':'13','zipno':POSTAL[district]} if district in POSTAL else CITY_QUERIES[district])}
    response=requests.get(API,params=params,timeout=(4,8))
    response.raise_for_status()
    reader=csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'),newline=''))
    if not reader.fieldnames or not any(str(k).startswith('OCCU_DESC') for k in reader.fieldnames):raise ValueError('Invalid TaiwanJobs CSV')
    raw=list(reader)
    keys={'occupation_title':'OCCU_DESC','work_location':'CITYNAME','salary_type':'SALARYCD','salary_lower':'NT_L','salary_upper':'NT_U','source_url':'URL_QUERY','updated_date':'TRANDATE','application_deadline':'STOP_DATE'}
    rows=[{key:next((v for k,v in row.items() if k and k.startswith(prefix)),None) for key,prefix in keys.items()} for row in raw]
    result=(rows,date.today().isoformat(),datetime.now(timezone.utc).isoformat(),'live',len(raw)>=1000)
    with _lock:_cache[district]=(time.monotonic(),result)
    return result


def snapshot_rows(district):
    with closing(sqlite3.connect(Path(DB_PATH).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as conn:
        conn.row_factory=sqlite3.Row
        where,params=('1=1',()) if district=='臺中市' else ('district=?',(district,))
        latest=conn.execute('SELECT MAX(snapshot_date) FROM official_job_vacancies WHERE '+where,params).fetchone()[0]
        rows=[dict(r) for r in conn.execute('SELECT * FROM official_job_vacancies WHERE '+where+' AND snapshot_date=?',(*params,latest))]
    return rows,latest,max((r['fetched_at'] for r in rows),default=None),'snapshot',True


def location_in(text):
    text=(text or '').replace('台','臺')
    text=re.sub(r'臺中(?![市縣])','臺中市',text)
    text=re.sub(r'臺北(?![市縣])','臺北市',text)
    exact=next((key for key in sorted(CITY_QUERIES,key=len,reverse=True) if key in text),None)
    if outside_scope(text):
        match=re.search(r'(?:臺北|新北|桃園|臺南|高雄|新竹|嘉義|基隆|宜蘭|苗栗|彰化|南投|雲林|屏東|花蓮|臺東|澎湖|金門|連江)[市縣](?:[^，。？?\s]{1,3}區)?',text)
        return exact or (match.group(0) if match else text[:80])
    return district_in(text) or exact


def _reference_for(role,area):
    try:result=fetch_rows(area)
    except (requests.RequestException,ValueError,UnicodeError,KeyError):
        if area not in POSTAL and area!='臺中市':return None
        try:result=snapshot_rows(area)
        except (sqlite3.Error,OSError):return None
    rows,snapshot,fetched,mode,cap=result
    return {'status':'available',**summarize(role,area,rows,snapshot=snapshot,fetched_at=fetched,mode=mode,cap_reached=cap)}


def get_reference(role,district):
    from concurrent.futures import ThreadPoolExecutor
    # Map pins are not salary scopes. Start at city level, never at a Taichung district.
    location=location_in(district) or '臺中市'
    requested=re.sub(r'(?<=[市縣]).*$', '',location) if outside_scope(location) else '臺中市'
    # The verified city-wide feeds are Taichung (city=13) and Hsinchu (postal=300).
    # Other explicitly requested cities continue to source-backed web search.
    stages=[['臺中市'],['新竹市']] if requested=='臺中市' else [['新竹市']] if requested=='新竹市' else []
    tried=[];best=None
    for areas in stages:
        areas=[a for a in areas if a not in tried]
        if not areas:continue
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda a:_reference_for(role,a),areas))
        tried.extend(areas)
        for ref in results:
            if ref and (best is None or ref['sample_count']>best['sample_count']):best=ref
            if ref and ref['sample_count']>=3:
                return {**ref,'requested_region':requested,'expanded':ref['region']!=('臺中市'+requested if requested in POSTAL else requested),'searched_regions':tried}
    if best and best['sample_count']:
        return {**best,'requested_region':requested,'expanded':best['region']!=('臺中市'+requested if requested in POSTAL else requested),'searched_regions':tried,'low_sample':True}
    return {'role':role,'status':'no_samples','requested_region':requested,'searched_regions':tried,'sources':[SOURCE,SURVEY],
            'notice':'已比對城市層級的薪資資料；可再參考下方台灣公開薪資調查來源。'}


def salary_answer(query):
    role=query_role(query)
    if not role:return None
    ref=get_reference(role,query)
    if ref['status']!='available':return None
    else:
        message=f"{ref['region']}｜{role}：{ref['sample_count']}筆有效月薪職缺，開價下限與上限各自中位數為新臺幣{ref['salary_min']:,}～{ref['salary_max']:,}元／月。\n資料日期：{ref['snapshot_date']}；讀取方式：{'即時接口（快取最多15分鐘）' if ref['mode']=='live' else '既有快照，非即時資料'}。\n"+ref['notice']
        if ref.get('expanded'):message=f"臺中市整體樣本不足，已擴大參考至{ref['region']}。\n"+message
        if ref.get('low_sample'):message+=' 樣本不足3筆，僅作個別職缺參考。'
        if ref['cap_reached']:message+=' 查詢可能受筆數上限限制，不代表完整市場。'
    return {'message':message,'sources':ref['sources'],'web_search_used':False,'salary_reference':ref}
