"""Lexical numeric guardrail, with separate metadata and user assumptions.

Exact quantity overlap is not semantic fact-checking. Display rounding is
limited to named monetary fields with explicit units. User-attributed conditions
are not tool observations; without user_query their input provenance is unknown.
"""
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, NamedTuple, Optional, Set


_NUMBER_RE = re.compile(
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|[+-]?\.\d+)"
    r"(?P<unit>\s*(?:萬(?:\s*[元人家筆個])?|[元人家筆個%％]))?"
)
_DATE_RE = re.compile(
    r"(?<![\d.])(?:\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r"|(?:民國\s*)?\d{3,4}\s*(?:學年度|年度|年)"
    r"(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?)?)(?!\d)"
)
_URL_RE = re.compile(r"https?://[^\s<>，。；（）()\[\]]+")
_UUID_RE = re.compile(r"\b[\da-fA-F]{8}(?:-[\da-fA-F]{4}){3}-[\da-fA-F]{12}\b")
_ID_RE = re.compile(
    r"(?:資料集(?:識別碼|編號|\s*ID)?|來源(?:識別碼|編號|\s*ID)"
    r"|統一編號|統編|公司編號|dataset_id|source_id)\s*(?:[:：#]|為|是)?\s*"
    r"(?P<id>[A-Za-z0-9][A-Za-z0-9_.-]*)", re.IGNORECASE
)
_DATE_FIELDS = {
    "date", "snapshot_date", "year_month", "period_start", "period_end",
    "latest_month", "missing_months", "data_period", "checked_at", "fetched_at",
    "loaded_at", "updated_at", "source_updated_at", "last_updated",
}
_DATE_COMPONENTS = {
    "year", "month", "day", "roc_year", "academic_year", "base_year",
    "projection_year", "snapshot_year", "snapshot_month", "snapshot_day",
    "period_start_year", "period_start_month", "period_end_year", "period_end_month",
    "latest_year", "latest_month_number",
}
_ID_FIELDS = {
    "tax_id", "company_id", "dataset_id", "dataset_ids", "source_dataset_id",
    "source_id", "source_ids",
}
_URL_FIELDS = {"source_url", "source_urls"}
_INPUT_FIELDS = {"query", "user_query", "user_conditions"}
_METRIC_EXCLUDED = _DATE_FIELDS | _DATE_COMPONENTS | _ID_FIELDS | _URL_FIELDS | _INPUT_FIELDS
_ROUNDING_FIELDS = {
    "average_insured_salary": ("平均投保薪資", "投保薪資平均值", "薪資基線"),
    "capital": ("資本總額", "資本額", "登記資本"),
}
_DISPLAY_CONNECTORS = (
    r"\s*(?:[：:=]|為|是|約|大約|約合|折合|取整|四捨五入|後"
    r"|新臺幣|新台幣|NT\$|TWD|\s)*$"
)
_USER_PREFIX_RE = re.compile(
    r"(?:"
    r"(?:您|你|使用者)(?:所)?(?:設定|提出|提供|提到)的?"
    r"(?:招募|招聘)?(?:需求|條件|目標|門檻|人數)?"
    r"|(?:您|你)的(?:招募|招聘)?(?:需求|條件|目標|門檻|人數)"
    r"|(?:您|你)(?:在[^，。；\n\d]{1,20})?(?:擴廠)?"
    r"(?:預計|計[畫劃]|想|要|希望)(?:招募|招|招聘|聘用)的?"
    r")(?:為|是|[:：])?\s*(?:招募|招)?\s*$"
)


class _Number(NamedTuple):
    start: int
    end: int
    value: Decimal
    display: Decimal
    unit: str
    scale: int


def _fields(data, key="", parent=None, excluded=_INPUT_FIELDS):
    """Walk scalar fields, retaining list field names and the owning record."""
    if isinstance(data, dict):
        for name, value in data.items():
            if name not in excluded:
                yield from _fields(value, name, data, excluded)
    elif isinstance(data, list):
        for value in data:
            yield from _fields(value, key, parent, excluded)
    else:
        yield key, data, parent


def _date_key(text):
    try:
        if re.search(r"\d{2}:\d{2}", text):
            value = datetime.fromisoformat(text.replace("/", "-").replace("Z", "+00:00"))
            if value.tzinfo:
                value = value.astimezone(timezone.utc)
            return ("timestamp", value.isoformat())
        parts = [int(part) for part in re.findall(r"\d+", text)]
        if "年" in text and (parts[0] < 1000 or "民國" in text):
            parts[0] += 1911
        date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
        return tuple(parts)
    except (ValueError, IndexError):
        return None


def _date_projections(key):
    if key is None:
        return set()
    if key[0] == "timestamp":
        # A timestamp's UTC normalization must not invent a source calendar day.
        # The recorded local date is added separately by the caller.
        return {key}
    return {key[:length] for length in range(1, len(key) + 1)}


def _structured_metadata(data):
    dates, identifiers, urls = set(), set(), set()
    for key, value, parent in _fields(data):
        if key in _ID_FIELDS and isinstance(value, (str, int)) and not isinstance(value, bool):
            identifiers.add(str(value))
        elif key in _URL_FIELDS and isinstance(value, str):
            urls.add(value)
        elif key in _DATE_FIELDS and isinstance(value, str):
            if key == "data_period" and re.fullmatch(r"\d{5}", value):
                dates.update(_date_projections(_date_key(f"民國{value[:3]}年{value[3:]}月")))
            for match in _DATE_RE.finditer(value):
                dates.update(_date_projections(_date_key(match.group())))
                if "T" in match.group() or ":" in match.group():
                    dates.update(_date_projections(_date_key(match.group()[:10])))
        elif key in _DATE_COMPONENTS and (key.endswith("year") or key == "year"):
            if isinstance(value, int) and not isinstance(value, bool):
                year = value + 1911 if 100 <= value < 1000 else value
                dates.update(_date_projections(_date_key(f"{year}年")))
                month_key = "month" if key in {"year", "roc_year"} else key[:-4] + "month"
                if key == "latest_year":
                    month_key = "latest_month_number"
                month = parent.get(month_key)
                day = parent.get(key[:-4] + "day")
                if isinstance(month, int) and not isinstance(month, bool):
                    period = f"{year}-{month}"
                    if isinstance(day, int) and not isinstance(day, bool):
                        period += f"-{day}"
                    dates.update(_date_projections(_date_key(period)))
    return dates, identifiers, urls


def _metadata_tokens(text):
    tokens = []
    # URLs and UUIDs contain date/number-looking fragments: consume them first.
    for kind, pattern in (("url", _URL_RE), ("id", _UUID_RE), ("id", _ID_RE), ("date", _DATE_RE)):
        for match in pattern.finditer(text):
            start, end = match.span("id") if pattern is _ID_RE else match.span()
            if kind == "id" and re.match(r"\s*(?:萬?[元人家筆個]|[%％])", text[end:]):
                continue
            if not any(start < right and end > left for left, right, _, _ in tokens):
                tokens.append((start, end, kind, text[start:end]))
    return tokens


def _number_tokens(text, metadata):
    cleaned = list(text)
    for start, end, _, _ in metadata:
        cleaned[start:end] = " " * (end - start)
    for match in _NUMBER_RE.finditer("".join(cleaned)):
        display = Decimal(match.group("number").replace(",", ""))
        unit = (match.group("unit") or "").strip().replace(" ", "")
        scale = 10000 if unit.startswith("萬") else 1
        yield _Number(match.start(), match.end(), display * scale, display, unit, scale)


def extract_numbers_from_text(text: str) -> List[float]:
    """Extract quantities; dates and labelled source/company IDs are metadata."""
    return [float(number.value) for number in _number_tokens(text, _metadata_tokens(text))]


def flatten_structured_numbers(data: Any) -> Set[float]:
    """Collect explicit quantities, without metadata, inputs or transformations."""
    return {
        float(value) for _, value, _ in _fields(data, excluded=_METRIC_EXCLUDED)
        if isinstance(value, (int, float))
        and not isinstance(value, bool) and Decimal(str(value)).is_finite()
    }


def _clause_prefix(text, start):
    return re.split(r"[，,。；;！？!?\n]", text[:start])[-1][-100:]


def _is_user_condition(text, number):
    prefix = _clause_prefix(text, number.start)
    suffix = re.split(r"[，,。；;！？!?\n]", text[number.end:])[0]
    return (
        number.unit in {"人", "元", "萬元", "家", "筆", "個", "%", "％"}
        and not re.search(r"官方|統計|工具|觀測|資料顯示", prefix + suffix)
        and (re.search(r"需求|條件|目標|門檻|人數|招募|招|招聘|聘用", prefix)
             or re.match(r"\s*(?:需求|條件|目標|門檻|人數)", suffix))
        and _USER_PREFIX_RE.search(prefix) is not None
    )


def _matches_rounding(text, number, fields):
    if number.unit not in {"元", "萬元"}:
        return False
    # 萬元 must retain at least two decimal places (precision of 100 元).
    if number.scale == 10000 and number.display.as_tuple().exponent > -2:
        return False
    prefix = _clause_prefix(text, number.start)
    for key, value, _ in fields:
        aliases = _ROUNDING_FIELDS.get(key)
        if not aliases or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not any(re.search(re.escape(label) + _DISPLAY_CONNECTORS, prefix) for label in aliases):
            continue
        try:
            truth = Decimal(str(value)) / number.scale
            precision = Decimal(1).scaleb(number.display.as_tuple().exponent)
            if truth.quantize(precision, rounding=ROUND_HALF_UP) == number.display:
                return True
        except InvalidOperation:
            pass
    return False


def verify_explanation_numbers(
    explanation_text: str,
    structured_data: Dict[str, Any],
    tolerance: float = 0.05,
    *,
    user_query: Optional[str] = None,
) -> Dict[str, Any]:
    """Audit quantities and metadata; explicitly attributed inputs are separate.

    Existing callers may omit user_query. In that case attributed conditions are
    recorded as unverified assumptions, never as matching tool observations.
    """
    metadata = _metadata_tokens(explanation_text)
    numbers = list(_number_tokens(explanation_text, metadata))
    truth_nums = flatten_structured_numbers(structured_data)
    dates, identifiers, urls = _structured_metadata(structured_data)
    fields = list(_fields(structured_data, excluded=_METRIC_EXCLUDED))
    query_nums = list(_number_tokens(user_query, _metadata_tokens(user_query))) if user_query is not None else None
    conditions, matched, unmatched = [], 0, []
    for number in numbers:
        if _is_user_condition(explanation_text, number) and (
            query_nums is None or any(
                number.value == query.value
                and number.unit.replace("萬", "") == query.unit.replace("萬", "")
                for query in query_nums
            )
        ):
            conditions.append(float(number.value))
            continue
        if any(abs(float(number.value) - truth) <= tolerance for truth in truth_nums) or _matches_rounding(explanation_text, number, fields):
            matched += 1
        else:
            unmatched.append(float(number.value))

    metadata_matched = 0
    for _, _, kind, value in metadata:
        supported = (
            _date_key(value) in dates if kind == "date"
            else value in urls if kind == "url"
            else value in identifiers
        )
        if supported:
            metadata_matched += 1
        else:
            unmatched.append(value)

    total = len(numbers) - len(conditions) + len(metadata)
    matched += metadata_matched
    details = []
    if conditions:
        provenance = "已比對原始提問數值" if user_query is not None else "未核對原始提問"
        details.append(f"{len(conditions)} 個明示的使用者條件另列為假設（{provenance}），不計入工具觀測值符合率。")

    if not structured_data or not (truth_nums or dates or identifiers or urls):
        status, accuracy, matched = "FAILED", 0.0 if total else None, 0
        details.append("沒有可供核對的工具數值或中繼資料；不能驗證模型回答。")
    elif not total:
        status, accuracy = "NOT_APPLICABLE", None
        details.append("回答沒有可比對的觀測數值；本檢查不代表語意或來源已驗證。")
    else:
        accuracy = round(matched / total * 100.0, 1)
        # Do not let a rounded accuracy of 100% hide any unsupported claim.
        status = "VERIFIED" if not unmatched else "WARNING" if accuracy >= 80.0 else "FAILED"
        details.append(f"數值與中繼資料比對完成：{matched}/{total} 項相符（符合率 {accuracy}%），其中日期／識別碼 {metadata_matched}/{len(metadata)} 項；此結果不核驗完整敘述的語意關係。")
    if unmatched:
        details.append(f"未完全比對數值或中繼資料：{unmatched[:5]}")
    return {
        "status": status,
        "matched_count": matched,
        "total_extracted": total,
        "accuracy_pct": accuracy,
        "metadata_count": len(metadata),
        "metadata_matched_count": metadata_matched,
        "user_condition_count": len(conditions),
        "audit_details": details,
    }
