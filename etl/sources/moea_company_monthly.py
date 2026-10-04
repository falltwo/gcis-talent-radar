"""Recover missing GCIS months from MOEA's official monthly workbooks.

These are observed statistics, not imputed values. Workbook headers, period,
city, numeric values and sector totals are checked before filling any gap.
"""
import re

import numpy as np
import pandas as pd

SHEETS = {"existing": "20211-01-01", "new": "20211-01-09", "dissolved": "20211-01-10"}
ALIASES = {"農林漁牧業": "農林漁牧業", "營建工程業": "營造業",
           "出版影音及資通訊業": "資訊及通訊傳播業", "教育業": "教育服務業"}
URLS = {"2014-11": "https://mnscdn.moea.gov.tw/MNS/DOS/content/wHandMenuFile.ashx?file_id=866",
        "2025-08": "https://mnscdn.moea.gov.tw/MNS/DOS/content/wHandMenuFile.ashx?file_id=37479",
        "2025-09": "https://mnscdn.moea.gov.tw/MNS/DOS/content/wHandMenuFile.ashx?file_id=37652"}
RECOVERY_METRICS = {"2014-11": ("existing",), "2025-08": tuple(SHEETS), "2025-09": tuple(SHEETS)}


def normalized(value):
    return re.sub(r"[\s、，,；;]", "", str(value))


def parse_workbook(path, year_month, metrics=None):
    year, month = map(int, year_month.split("-"))
    rows = []
    book = pd.ExcelFile(path)
    for metric in (metrics or SHEETS):
        sheet = SHEETS[metric]
        if sheet not in book.sheet_names:
            sheet = sheet.replace("20211-01", "2491-00")
        frame = pd.read_excel(book, sheet_name=sheet, header=None)
        text = " ".join(str(x) for x in frame.iloc[:5].to_numpy().flat)
        if not re.search(rf"{year - 1911}年0?{month}月", text):
            raise ValueError(f"Wrong workbook month: {path}")
        if "新臺幣百萬元" not in text or "按行業別及縣" not in text:
            raise ValueError(f"Unexpected workbook scope/unit: {sheet}")
        city_rows = frame[frame.iloc[:, 0].map(normalized) == "臺中市"]
        if len(city_rows) != 1:
            raise ValueError("Expected exactly one Taichung row")
        city = city_rows.iloc[0]
        if normalized(city.iloc[22]) != "臺中市":
            raise ValueError("Continuation table city differs")
        parsed = []
        for col in range(frame.shape[1] - 1):
            if normalized(frame.iloc[7, col]) != "家數":
                continue
            if normalized(frame.iloc[7, col + 1]) != "資本額":
                raise ValueError("Missing paired capital column")
            label = normalized("".join(str(frame.iloc[r, col]) for r in (5, 6)
                                      if pd.notna(frame.iloc[r, col])))
            industry = ALIASES.get(label, label)
            count, capital = float(city.iloc[col]), float(city.iloc[col + 1])
            if not np.isfinite([count, capital]).all() or count < 0 or count != int(count):
                raise ValueError(f"Invalid observed cells: {industry}")
            parsed.append({"year_month": year_month, "industry": industry, "metric": metric,
                           "companies": int(count), "capital_million_twd": capital,
                           "quality_flag": "official_monthly_recovered"})
        if len(parsed) != 21 or len({r["industry"] for r in parsed}) != 21:
            raise ValueError("Unexpected industry schema")
        total = next(r for r in parsed if r["industry"] == "總計")
        sectors = [r for r in parsed if r["industry"] != "總計"]
        if sum(r["companies"] for r in sectors) != total["companies"]:
            raise ValueError("Industry company counts do not sum to total")
        if not np.isclose(sum(r["capital_million_twd"] for r in sectors),
                          total["capital_million_twd"], atol=1e-5, rtol=0):
            raise ValueError("Industry capital does not sum to total")
        rows.extend(parsed)
    return pd.DataFrame(rows)


def fill_official_gaps(frame, recovered):
    keys = ["year_month", "industry", "metric"]
    if recovered.duplicated(keys).any():
        raise ValueError("Duplicate recovered keys")
    result = frame.set_index(keys).copy()
    for key, row in recovered.set_index(keys).iterrows():
        if key not in result.index:
            raise ValueError(f"Recovered key absent from original data: {key}")
        if pd.notna(result.loc[key, "companies"]):
            raise ValueError(f"Refusing to replace existing observation: {key}")
        result.loc[key, ["companies", "capital_million_twd", "quality_flag"]] = row[
            ["companies", "capital_million_twd", "quality_flag"]].values
    return result.reset_index().sort_values(["metric", "industry", "year_month"])


