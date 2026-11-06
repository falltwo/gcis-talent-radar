"""
E5a：經濟部工廠校正統計調查（EE520）— 臺中市 29 區 × 製造業中類 × 年
https://service.moea.gov.tw/EE520/investigate/InvestigateG.aspx

ASP.NET 表單查詢，用 Scrapling FetcherSession（一般模式）每區送一次：
勾選「營運中工廠家數、年底從業員工人數」× 全部製造業中類 ×（該區），年份取全部可選範圍。

輸出 tc_factory_district_industry_annual

另抓官方總計（fetch_totals，兩次查詢），給區位商數 LQ 當分母：各區細格有保密，自己加總湊不出總數。
- tc_factory_district_total_annual：29 區 ×「(C)製造業」大類（區總計）
- tc_factory_city_industry_annual：臺中市 ×（大類＋各中類）
- 「*」＝未滿 4 家保密 → NaN，flag=suppressed_lt4；「-」＝無數值 → NaN，flag=no_value
- 85、90、95、100、105、110 年為工商普查年，原站沒有資料（不補）
- 科學園區、科技產業園區的工廠已併入所在行政區
"""
import html
import io
import re
import time
import unicodedata

import numpy as np
import pandas as pd

from etl.sources.common import RAW_DATA_DIR, TAICHUNG_DISTRICTS, _record, write_processed

URL = "https://service.moea.gov.tw/EE520/investigate/InvestigateG.aspx"
RAW = RAW_DATA_DIR / "moea_ee520"
TOTALS_RAW = RAW_DATA_DIR / "moea_ee520_totals"   # 另放一個資料夾，transform() 只讀逐區的 29 個檔
ITEMS = ["營運中工廠家數", "年底從業員工人數"]
SOURCE = "經濟部統計處 工廠校正統計調查（EE520 InvestigateG）"
# 行業統計分類第 11 次修正 製造業中類（EE520 查詢頁行業樹的名稱與代碼）
INDUSTRY_CODES = {
    "食品及飼品業": "08", "飲料及菸草業": "09", "紡織業": "11", "成衣及服飾品業": "12", "皮革毛皮製品業": "13",
    "木竹製品業": "14", "紙漿、紙及紙製品業": "15", "印刷及資料儲存媒體複製業": "16", "石油及煤製品業": "17",
    "化學材料及肥料業": "18", "其他化學製品業": "19", "藥品及醫用化學製品業": "20", "橡膠製品業": "21",
    "塑膠製品業": "22", "非金屬礦物製品業": "23", "基本金屬業": "24", "金屬製品業": "25", "電子零組件業": "26",
    "電腦電子產品及光學製品業": "27", "電力設備及配備業": "28", "機械設備業": "29", "汽車及其零件業": "30",
    "其他運輸工具及其零件業": "31", "家具業": "32", "其他製造業": "33", "產業用機械設備維修及安裝業": "34",
}


def _text(page):
    return html.unescape(page.body.decode("utf-8", "ignore"))


def _nodes(t, tree):
    return re.findall(r'id="ContentPlaceHolder1_' + tree + r't(\d+)"[^>]*>([^<]*)</a>', t)


def _form(t):
    data = dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', t))
    for name, body in re.findall(r'<select name="([^"]+)"[^>]*>(.*?)</select>', t, re.S):
        sel = re.search(r'<option selected="selected" value="([^"]*)"', body) or re.search(r'<option value="([^"]*)"', body)
        data[name] = sel.group(1) if sel else ""
    return data


def _year_range(t):
    body = re.search(r'<select name="ctl00\$ContentPlaceHolder1\$ddlDateBeg"[^>]*>(.*?)</select>', t, re.S).group(1)
    years = sorted(re.findall(r'<option[^>]*value="(\d+)"', body), key=int)
    return years[0], years[-1]


def _query(s, t, item_nodes, industry_nodes, region_nodes):
    """勾選項目、行業、地區，年份取全部可選範圍，送出查詢並回傳結果頁。"""
    beg, end = _year_range(t)
    data = _form(t)
    data.update({"ctl00$ContentPlaceHolder1$ddlDateKind": "民國",
                 "ctl00$ContentPlaceHolder1$ddlDateBeg": beg, "ctl00$ContentPlaceHolder1$ddlDateEnd": end,
                 "ctl00$ContentPlaceHolder1$ddlQueryKind": "R", "ctl00$ContentPlaceHolder1$btnQuery": "查詢",
                 "__EVENTTARGET": "", "__EVENTARGUMENT": ""})
    for tree, nodes in (("tvItem1", item_nodes), ("tvItem2", industry_nodes), ("tvItem3", region_nodes)):
        for n in nodes:
            data[f"ContentPlaceHolder1_{tree}n{n}CheckBox"] = "on"
    out = _text(s.post(URL, data=data, timeout=180))
    if "ContentPlaceHolder1_tabResult" not in out:
        raise RuntimeError("EE520 查詢沒有結果表")
    return out, beg, end


def _taichung(t):
    """地區樹裡「台中市」節點，以及它之後的 29 個行政區節點（其他縣市也有「東區」「北區」…）。"""
    region = _nodes(t, "tvItem3")
    tc = next(i for i, (_, l) in enumerate(region) if l.strip() in ("台中市", "臺中市"))
    # 兩字區名中間是全形空白（「中　區」），比對前去掉所有空白
    districts = {re.sub(r"\s", "", l): n for n, l in region[tc + 1:tc + 30]}
    return region[tc][0], districts


def fetch_totals():
    """兩次查詢：29 區 × 製造業大類（區總計），以及臺中市 ×（大類＋各中類）。"""
    from scrapling.fetchers import FetcherSession

    TOTALS_RAW.mkdir(parents=True, exist_ok=True)
    with FetcherSession() as s:
        for name in ("district_total", "city_industry"):
            t = _text(s.get(URL, timeout=60))
            items = [n for n, l in _nodes(t, "tvItem1") if l.strip() in ITEMS]
            total = [n for n, l in _nodes(t, "tvItem2") if l.strip() == "(C)製造業"]
            inds = [n for n, l in _nodes(t, "tvItem2") if re.match(r"^\((\d{2})\)", l.strip())]
            city, districts = _taichung(t)
            if len(total) != 1 or len(districts) != len(TAICHUNG_DISTRICTS):
                raise RuntimeError(f"EE520 查詢頁結構變了：大類 {len(total)} 個、行政區 {len(districts)} 個")
            if name == "district_total":
                out, beg, end = _query(s, t, items, total, [districts[d] for d in TAICHUNG_DISTRICTS])
            else:
                out, beg, end = _query(s, t, items, total + inds, [city])
            path = TOTALS_RAW / f"{name}.html"
            path.write_text(out, encoding="utf-8")
            _record("moea_ee520", f"{URL} [POST {name} 年={beg}-{end}]", path, out.encode("utf-8"))
            print(f"  ↓ {name}（{beg}–{end} 年）")
            time.sleep(2)


def fetch_all(delay: float = 2.0):
    from scrapling.fetchers import FetcherSession

    RAW.mkdir(parents=True, exist_ok=True)
    with FetcherSession() as s:
        for district in TAICHUNG_DISTRICTS:
            path = RAW / f"{district}.html"
            if path.exists():
                continue
            t = _text(s.get(URL, timeout=60))
            items = [n for n, l in _nodes(t, "tvItem1") if l.strip() in ITEMS]
            inds = [n for n, l in _nodes(t, "tvItem2") if re.match(r"^\((\d{2})\)", l.strip())]
            _, districts = _taichung(t)
            out, beg, end = _query(s, t, items, inds, [districts[district]])
            path.write_text(out, encoding="utf-8")
            _record("moea_ee520", f"{URL} [POST 區={district} 年={beg}-{end} 中類={len(inds)}]", path, out.encode("utf-8"))
            print(f"  ↓ {district}（{len(inds)} 個中類，{beg}–{end} 年）")
            time.sleep(delay)


def _parse(path, levels=3):
    """表頭 3 層：項目、中類、地區。勾了大類又勾中類時是 4 層：項目、大類、中類（大類總計欄空白）、地區。"""
    t = path.read_text(encoding="utf-8")
    table = re.search(r'<table id="ContentPlaceHolder1_tabResult".*?</table>', t, re.S).group(0)
    df = pd.read_html(io.StringIO(table), header=list(range(levels)), index_col=0, keep_default_na=False)[0]
    df = df.loc[df.index.astype(str).str.match(r"^\d+年$")]
    rows = []
    for (item, *groups, district), col in df.items():
        industry = next((g for g in reversed(groups) if not str(g).startswith("Unnamed")), "")
        item = re.sub(r"\s*\(.*\)$", "", str(item))   # 「營運中工廠家數 (家)」→「營運中工廠家數」
        if item not in ITEMS:
            continue
        for year, raw in col.items():
            raw = str(raw).strip().replace(",", "")
            flag = "suppressed_lt4" if raw == "*" else "no_value" if raw in ("-", "") else ""
            # NFKC：原站部分字用相容字元（例：「料」U+F9BE），外觀相同但比對不到
            rows.append({"roc_year": int(str(year)[:-1]),
                         "district": unicodedata.normalize("NFKC", re.sub(r"\s", "", str(district))),
                         "industry": unicodedata.normalize("NFKC", re.sub(r"\s", "", str(industry))),
                         "item": item, "value": float(raw) if not flag else np.nan, "flag": flag})
    return rows


def _wide(long, key):
    long = long.copy()
    long["metric"] = long["item"].map({"營運中工廠家數": "factories", "年底從業員工人數": "employees"})
    if long.duplicated(key + ["metric"]).any():
        raise ValueError("EE520 同一格出現兩次")
    val = long.pivot(index=key, columns="metric", values="value")
    flag = long.pivot(index=key, columns="metric", values="flag").add_suffix("_flag")
    df = val.join(flag).reset_index()
    df.insert(1, "year", df["roc_year"] + 1911)
    return df


def transform_totals():
    """官方總計：區總計只取製造業大類；全市取大類（industry_code C）與各中類。保密格照樣留 NaN。"""
    district = pd.DataFrame(_parse(TOTALS_RAW / "district_total.html"))
    district = district[(district.industry == "製造業") & district.district.isin(TAICHUNG_DISTRICTS)]
    if set(district.district) != set(TAICHUNG_DISTRICTS):
        raise ValueError(f"區總計缺區：{sorted(set(TAICHUNG_DISTRICTS) - set(district.district))}")
    district = _wide(district, ["roc_year", "district"]).sort_values(["district", "roc_year"]).reset_index(drop=True)
    city = pd.DataFrame(_parse(TOTALS_RAW / "city_industry.html", levels=4))
    city = _wide(city[city.district.isin(["台中市", "臺中市"])], ["roc_year", "industry"])
    city.insert(city.columns.get_loc("industry"), "industry_code", city["industry"].map({**INDUSTRY_CODES, "製造業": "C"}))
    unknown = sorted(city.loc[city.industry_code.isna(), "industry"].unique())
    if unknown:
        raise ValueError(f"未知中類名稱：{unknown}")
    city = city.sort_values(["industry_code", "roc_year"]).reset_index(drop=True)
    notes = ["factories_flag／employees_flag：suppressed_lt4＝未滿 4 家保密；no_value＝原站無數值",
             "區位商數 LQ 的分母：各區細格有保密，自己加總湊不出總數，所以另取官方總計"]
    write_processed(district, "tc_factory_district_total_annual", sources=[SOURCE, URL],
                    grain="臺中市行政區 × 年（民國），製造業大類總計", notes=notes)
    write_processed(city, "tc_factory_city_industry_annual", sources=[SOURCE, URL],
                    grain="臺中市 × 製造業大類與中類 × 年（民國）", notes=notes)
    return district, city


def transform():
    files = sorted(RAW.glob("*.html"))
    if len(files) != len(TAICHUNG_DISTRICTS):
        print(f"  ⚠ 只有 {len(files)}/{len(TAICHUNG_DISTRICTS)} 區的原始檔")
    long = pd.DataFrame([r for p in files for r in _parse(p)])
    df = _wide(long, ["roc_year", "district", "industry"])
    df.insert(df.columns.get_loc("industry"), "industry_code", df["industry"].map(INDUSTRY_CODES))
    unknown = sorted(df.loc[df.industry_code.isna(), "industry"].unique())
    if unknown:
        raise ValueError(f"未知中類名稱：{unknown}")
    df = df.sort_values(["district", "industry_code", "roc_year"]).reset_index(drop=True)
    years = sorted(df.roc_year.unique())
    write_processed(df, "tc_factory_district_industry_annual",
                    sources=[SOURCE, URL], grain="臺中市行政區 × 製造業中類 × 年（民國）",
                    notes=[f"年份：{years[0]}–{years[-1]}，共 {len(years)} 年；工商普查年（85、90、95、100、105、110）原站無資料",
                           "factories_flag／employees_flag：suppressed_lt4＝未滿 4 家保密；no_value＝原站無數值",
                           "科學園區、科技產業園區工廠已併入所在行政區"])
    return df


if __name__ == "__main__":
    fetch_all()
    transform()
    fetch_totals()
    transform_totals()
