"""
F4／F5：臺中市就業市場分析報告（季報，臺中市政府勞工局）
來源列表頁只有網頁，用 Scrapling Fetcher 抓（一般模式，每次間隔 2 秒）。

輸出
- tc_jobmarket_monthly        表 1：每月新登記／有效 求職、求才、推介、僱用與求供倍數（109-01 起）
- tc_jobmarket_occupation_q   表 4：按職業別（季合計，**不可攤到月**）
- tc_jobmarket_industry_q     表 8：熱門行業新登記求才人數（季）
- tc_jobmarket_top_jobs_q     表 9：求職者希望職類前 20 名與求供倍數（季）

口徑限制：只涵蓋臺中市府所轄就業服務據點（含勞動部委辦站），111 年起委辦範圍擴大，前後不可直接比較。
"""
import re
from urllib.parse import unquote, urljoin

import numpy as np
import pandas as pd
import pdfplumber

from etl.sources.common import RAW_DATA_DIR, write_processed

LIST_URL = "https://www.labor.taichung.gov.tw/1229008/1229009/822283/822308/822323/post"
RAW = RAW_DATA_DIR / "taichung_labor_reports"
SOURCE = "臺中市政府勞工局 臺中市就業市場分析報告（季報）"
OCCUPATIONS = [
    "民意代表、主管及經理人員", "專業人員", "技術員及助理專業人員", "事務支援人員",
    "服務及銷售工作人員", "農、林、漁、牧業生產人員", "技藝有關工作人員",
    "機械設備操作及組裝人員", "基層技術工及勞力工",
]
MONTHLY_COLS = ["new_seekers", "active_seekers", "new_openings", "active_openings", "new_seekers_placed",
                "active_seekers_placed", "new_openings_filled", "active_openings_filled",
                "openings_per_seeker", "placement_rate_pct", "fill_rate_pct"]
SCOPE_BREAK = "2022-01"   # 111 年起市府接手勞動部臺中就業中心委辦業務


def num(s):
    if s is None:
        return np.nan
    s = str(s).replace(",", "").replace("%", "").strip()
    return np.nan if s in ("", "-", "－") else float(s)


def fetch_all():
    from scrapling.fetchers import Fetcher
    import time
    from etl.sources.common import _record

    page = Fetcher.get(LIST_URL, timeout=60)
    if page.status != 200:
        raise RuntimeError(f"列表頁回應 {page.status}")
    reports = {}
    for a in page.css("a"):
        href = a.attrib.get("href") or ""
        m = re.match(r"(\d{3})年第(\d)季臺中市就業市場分析報告\.pdf$", unquote(href.rsplit("/", 1)[-1]))
        if m:
            reports[(int(m.group(1)), int(m.group(2)))] = urljoin(LIST_URL, href)
    print(f"列表頁找到 {len(reports)} 份季報")
    RAW.mkdir(parents=True, exist_ok=True)
    for (y, q), url in sorted(reports.items()):
        path = RAW / f"{y}Q{q}.pdf"
        if path.exists():
            continue
        resp = Fetcher.get(url, timeout=120)
        if resp.status != 200 or not resp.body.startswith(b"%PDF"):
            print(f"  ✗ {y}Q{q} 下載失敗（{resp.status}）")
            continue
        path.write_bytes(resp.body)
        _record("taichung_labor_reports", url, path, resp.body)
        print(f"  ↓ {y}Q{q}")
        time.sleep(2)


def _cells(row):
    return [c for c in row if c not in (None, "")]


def parse_monthly(tables, roc_year, quarter):
    """表 1：列首是月份數字（或『第』＝季合計），後面 11 個數值"""
    out = []
    months = [3 * (quarter - 1) + i for i in (1, 2, 3)]
    for table in tables:
        month_rows = 0
        for row in table:
            cells = [re.sub(r"\s+", "", str(c)) for c in _cells(row)]
            vals = [c for c in cells if re.fullmatch(r"[\d,]+(\.\d+)?%?|-", c)]
            is_total = any(c.startswith("第") for c in cells[:3])
            if is_total and len(vals) >= 11:
                rest, month = vals[:11], None
            elif len(vals) >= 12 and vals[0].isdigit() and month_rows < 3:
                # 月份欄有時被折行（10 → 「1」「0」），依列序決定是季內第幾個月，並核對標籤開頭
                month = months[month_rows]
                if not str(month).startswith(vals[0]):
                    continue
                rest = vals[1:12]
                month_rows += 1
            else:
                continue
            rec = dict(zip(MONTHLY_COLS, map(num, rest)))
            # 檢核：求供倍數 = 新登記求才 / 新登記求職
            if rec["new_seekers"] and abs(rec["new_openings"] / rec["new_seekers"] - rec["openings_per_seeker"]) > 0.011:
                continue
            ad = roc_year + 1911
            out.append({"period": f"{ad}-{month:02d}" if month else f"{ad}Q{quarter}",
                        "is_quarter_total": month is None, **rec})
    # 同一期出現多次（跨頁重複抽到）只留第一次
    seen, uniq = set(), []
    for r in out:
        if r["period"] not in seen:
            seen.add(r["period"])
            uniq.append(r)
    return uniq


def parse_occupation(tables):
    """表 4：舊版 PDF 折行時會重複數值，用 求供倍數=B/A、就業率=C/A 反推正確欄位"""
    for table in tables:
        if not any(r and r[0] and "職業別" in str(r[0]) for r in table):
            continue
        rows = []
        for row in table:
            cells = [re.sub(r"\s+", "", str(c)) for c in row if c not in (None, "")]
            if not cells:
                continue
            label = cells[0]   # 新版在第 1 欄，舊版在第 2 欄（第 1 欄空白）
            occ = next((o for o in OCCUPATIONS if label[:4] == o[:4]), None)
            if not occ:
                continue
            vals = cells[1:]
            ints = [num(c) for c in vals if "%" not in c and "." not in c]
            ratio = next((num(c) for c in vals if "." in c and "%" not in c), np.nan)
            pcts = [num(c) for c in vals if "%" in c]
            # 兩道檢核：先比 求供倍數=B/A；舊版 PDF 偶有倍數欄錯列，再退而比 就業率=C/A，通過就重算倍數
            candidates = [idx for idx in ([0, 1, 2, 3], [0, 1, 3, 4], [0, 2, 3, 5], [0, 1, 3, 5], [0, 2, 4, 5])
                          if max(idx) < len(ints) and ints[idx[0]]]
            best, check = None, None
            for idx in candidates:
                a, b, c, d = (ints[i] for i in idx)
                if not np.isnan(ratio) and abs(b / a - ratio) <= 0.011:
                    best, check = (a, b, c, d), "ratio"
                    break
            if best is None and pcts:
                for idx in candidates:
                    a, b, c, d = (ints[i] for i in idx)
                    if abs(c / a * 100 - pcts[0]) <= 0.02:
                        best, check = (a, b, c, d), "rate_ratio_recomputed"
                        break
            if best:
                a, b, c, d = best
                rows.append({"occupation": occ, "new_seekers": a, "new_openings": b, "active_seekers_placed": c,
                             "active_openings_filled": d,
                             "openings_per_seeker": ratio if check == "ratio" else round(b / a, 2),
                             "parse_check": check})
        return rows
    return []


def parse_industry(text):
    m = re.search(r"熱門行業\s*\n?單位：人\s*\n?排名\s*行業\s*求才新登記人數(.*?)資料來源", text, re.S)
    if not m:
        return []
    return [{"rank": int(r), "industry": i.strip(), "new_openings": num(n)}
            for r, i, n in re.findall(r"(\d{1,2})\s+([^\d\n]+?)\s+([\d,]+)\s*\n", m.group(1) + "\n")]


def parse_top_jobs(text):
    """表 9：求職排名 求才排名 職類 求職人數 求才人數 求供倍數"""
    out = []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d{1,2})\s+(\d{1,3})\s+(\S.*?)\s+([\d,]+)\s+([\d,]+)\s+([\d.]+|-)\s*$", line)
        if m:
            rk_s, rk_o, job, a, b, ratio = m.groups()
            out.append({"seeker_rank": int(rk_s), "opening_rank": int(rk_o), "job": job,
                        "seekers": num(a), "openings": num(b), "openings_per_seeker": num(ratio)})
    return out


def transform():
    monthly, occ, ind, top, problems = [], [], [], [], []
    files = sorted(RAW.glob("*.pdf"))
    if not files:
        raise FileNotFoundError(f"{RAW} 沒有 PDF，請先 fetch")
    for path in files:
        y, q = map(int, re.match(r"(\d{3})Q(\d)", path.stem).groups())
        with pdfplumber.open(path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            tables = [t for p in pdf.pages for t in p.extract_tables()]
        base = {"roc_year": y, "quarter": q, "source_pdf": path.name}
        m = parse_monthly(tables, y, q)
        monthly += [{**base, **r} for r in m]
        if sum(not r["is_quarter_total"] for r in m) != 3:
            problems.append(f"{path.stem} 表1 月資料 {sum(not r['is_quarter_total'] for r in m)}/3")
        o = parse_occupation(tables)
        occ += [{**base, **r} for r in o]
        if len(o) != len(OCCUPATIONS):
            problems.append(f"{path.stem} 表4 職業別 {len(o)}/{len(OCCUPATIONS)}")
        i = parse_industry(text)
        ind += [{**base, **r} for r in i]
        if not i:
            problems.append(f"{path.stem} 表8 熱門行業 0 列")
        t = parse_top_jobs(text)
        top += [{**base, **r} for r in t]
        if len(t) < 15:
            problems.append(f"{path.stem} 表9 熱門職缺 {len(t)}/20")

    mdf = pd.DataFrame(monthly)
    mdf["scope_period"] = np.where(mdf["period"].str[:7] < SCOPE_BREAK, "before_2022", "from_2022")
    # 檢核：三個月加總 = 季合計（新登記求職、求才）
    for (y, q), g in mdf.groupby(["roc_year", "quarter"]):
        tot, mon = g[g.is_quarter_total], g[~g.is_quarter_total]
        if len(tot) == 1 and len(mon) == 3:
            for col in ("new_seekers", "new_openings"):
                if abs(mon[col].sum() - tot[col].iloc[0]) > 1:
                    problems.append(f"{y}Q{q} {col} 月加總 {mon[col].sum():.0f} ≠ 季合計 {tot[col].iloc[0]:.0f}")
    notes = ["只涵蓋臺中市府所轄就業服務據點，不代表全部雇主職缺",
             f"{SCOPE_BREAK} 起委辦範圍擴大（scope_period 欄），前後不可直接比較",
             "表 4 職業別是季合計，不可攤到月"] + (["解析問題：" + "；".join(problems)] if problems else [])
    common = dict(sources=[SOURCE, LIST_URL])
    write_processed(mdf, "tc_jobmarket_monthly", grain="臺中市 × 月（另含季合計列 is_quarter_total）", notes=notes, **common)
    write_processed(pd.DataFrame(occ), "tc_jobmarket_occupation_q", grain="臺中市 × 季 × 職業大類", notes=notes, **common)
    write_processed(pd.DataFrame(ind), "tc_jobmarket_industry_q", grain="臺中市 × 季 × 行業大類（熱門行業排名）", notes=notes, **common)
    write_processed(pd.DataFrame(top), "tc_jobmarket_top_jobs_q", grain="臺中市 × 季 × 職類（前 20 名）", notes=notes, **common)
    if problems:
        print("  ⚠ 解析問題：", "；".join(problems))
    return mdf


if __name__ == "__main__":
    fetch_all()
    transform()
