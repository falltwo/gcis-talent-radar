"""Explicit geographic boundaries and deterministic vacancy comparisons."""
import re

from config import TAICHUNG_DISTRICTS


OTHER_CITIES = (
    "台北", "臺北", "新北", "桃園", "高雄", "台南", "臺南", "基隆", "新竹",
    "苗栗", "彰化", "南投", "雲林", "嘉義", "屏東", "宜蘭", "花蓮", "台東", "臺東",
    "澎湖", "金門", "連江", "Taipei", "Kaohsiung", "Tainan", "Taoyuan",
)


def unsupported_geography(query):
    """Detect an unsupported requested geography without treating brands as places.

    Bare place words such as ``台北富邦`` and ``新竹物流`` can be company names.
    When the query already identifies Taichung, only an explicit outside city/county
    marker or an unsupported district is enough to reject it.
    """
    if not re.search(r"職缺|就業|薪資|缺工|人力|工廠|新設|行政區|vacanc|workforce|jobs", query, re.I):
        return False
    text = query.lower()
    taichung_requested = "台中" in text or "臺中" in text or any(
        district in query for district in TAICHUNG_DISTRICTS
    )
    explicit_other_region = any(
        re.search(rf"{re.escape(city.lower())}(?:市|縣)", text)
        for city in OTHER_CITIES
    )
    outside_city_district = any(
        re.search(rf"{re.escape(city.lower())}[\u4e00-\u9fff]{{1,3}}區", text)
        for city in OTHER_CITIES
    )
    if explicit_other_region or outside_city_district:
        return True
    districts = re.findall(r"[\u4e00-\u9fff]{2,3}區", query)
    unsupported_district = any(
        not d.endswith(("行政區", "工業區", "兩區", "各區", "地區", "園區", "全區"))
        and not any(d.endswith(known) for known in TAICHUNG_DISTRICTS) for d in districts
    )
    if unsupported_district:
        return True
    return not taichung_requested and any(city.lower() in text for city in OTHER_CITIES)


def vacancy_comparison(results):
    """Return a supported comparison, or an explicit inability to compare."""
    jobs = [r for r in results if r.get("tool") == "get_regional_job_demand"]
    if len(jobs) < 2:
        return None
    data = [r.get("data") or {} for r in jobs]
    if any(not d.get("available") for d in data):
        return "其中一個地區沒有可用職缺資料，目前無法比較；沒有資料不代表職缺為零。"
    keys = ("snapshot_date", "industry_id", "retrieval_terms")
    if any(any(d.get(key) != data[0].get(key) for key in keys) for d in data[1:]):
        return "兩區的快照日期或職務篩選條件不同，目前不能直接比較。請使用相同日期與條件查詢。"
    if any(not d.get("district") for d in data) or len({d['district'] for d in data}) != len(data):
        return "比較需要不同的行政區與相同篩選條件，不能把全市和單一行政區直接比較。"
    if any(not isinstance(d.get(k), int) or isinstance(d.get(k), bool) or d[k] < 0
           for d in data for k in ("vacancy_postings", "requested_workers")):
        return "職缺資料的計量欄位不完整，目前無法比較。"
    lines = ["比較台中同一快照、相同職務篩選條件的可觀測資料："]
    for d in data:
        lines.append(f"{d['district']}：刊登職缺 {d['vacancy_postings']} 筆；需求人數 {d['requested_workers']} 人。")
    for key, label in (("vacancy_postings", "刊登筆數"), ("requested_workers", "需求人數")):
        maximum = max(d[key] for d in data)
        winners = [d['district'] for d in data if d[key] == maximum]
        lines.append(f"{label}：{'、'.join(winners)}最多。" if len(winners) < len(data) else f"{label}相同。")
    terms = data[0].get("retrieval_terms") or []
    lines.append("職務文字篩選：" + ("、".join(terms) if terms else "未篩選") + "。")
    lines.append("一筆刊登可招多人，因此兩個指標的排名可能不同。這是公開職缺快照，不是實際缺工或招募成功率；職務文字篩選也不是雇主行業分類。")
    if any(d.get("limit_reached_districts") for d in data):
        lines.append("查詢達到筆數上限，以上僅比較可觀測樣本，不能代表全區總數。")
    return "\n".join(lines)
