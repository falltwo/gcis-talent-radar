"""Read-only, release-bound GCIS context for an expansion comparison report.

City statistics and classified registry samples deliberately remain separate.
No function in this module downloads data, updates ETL output, or estimates jobs.
Every file is parsed from the same bytes that are hashed in the manifest.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


BASE = Path(__file__).resolve().parents[1]
RULES_VERSION = "gcis-report-v1"
CITY_URL = "https://data.gcis.nat.gov.tw/od/detail?oid=01E5CFC6-9F09-4CB5-BE81-22B451E4B1BD"
LIST_IDS = {
    "setup": "AD28285B-7B0E-4241-9F58-F2F0F289333E",
    "dissolved": "4302E583-A7B5-4BE2-A3D6-9707B1AACE1C",
    "change": "75353060-3C3D-453E-8E5C-4ADDEAA8260F",
}
DATE_COLUMNS = {"setup": "核准設立日期", "dissolved": "核准解散日期", "change": "核准變更日期"}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
CITY_INDUSTRIES = {"製造業", "C製造業", "Ｃ製造業"}


def _current_month() -> str:
    return datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m")


def _month_shift(month: str, delta: int) -> str:
    year, number = map(int, month.split("-"))
    index = year * 12 + number - 1 + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _months(start: str, end: str) -> list[str]:
    out = []
    while start <= end:
        out.append(start)
        start = _month_shift(start, 1)
    return out


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp950"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Undecodable GCIS CSV")


def _integer(value: Any) -> int | None:
    try:
        text = str(value).strip().replace(",", "")
        if not text or text.lower() in {"nan", "none", "null"}:
            return None
        number = Decimal(text)
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            return None
        return int(number)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _event_date(value: str) -> str | None:
    text = str(value or "").strip()
    try:
        if re.fullmatch(r"\d{7}", text):
            return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7])).isoformat()
        return date.fromisoformat(text).isoformat()
    except (ValueError, TypeError):
        return None


class _Capture:
    def __init__(self):
        self.manifest: list[dict] = []
        self.cache: dict[str, bytes] = {}

    def read(self, path: Path, role: str, source_url: str | None = None) -> bytes:
        key = str(path.resolve())
        if key not in self.cache:
            content = path.read_bytes()
            self.cache[key] = content
            self.manifest.append({
                "source_id": role, "path": key,
                "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
                "source_url": source_url, "published_at": None,
                "capture_kind": "LOCAL_RETAINED_BYTES",
            })
        return self.cache[key]

    def csv(self, path: Path, role: str, source_url: str | None = None) -> list[dict]:
        content = self.read(path, role, source_url)
        return list(csv.DictReader(io.StringIO(_decode(content)), strict=True))


def _attach_provenance(capture: _Capture, raw: Path) -> None:
    """Distinguish retained filtered bytes from the upstream-download hash."""
    path = raw / "_manifest.csv"
    if not path.exists():
        return
    try:
        metadata = capture.csv(path, "gcis_retained_source_manifest")
    except (OSError, ValueError, csv.Error):
        return
    lookup = {}
    for row in metadata:
        recorded_path = str(row.get("path", "")).replace("\\", "/")
        if "/raw/" in recorded_path:
            lookup[recorded_path.split("/raw/", 1)[1]] = row
    root = raw.resolve()
    for entry in capture.manifest:
        try:
            key = Path(entry["path"]).relative_to(root).as_posix()
        except ValueError:
            continue
        row = lookup.get(key)
        if row:
            entry.update(source_url=row.get("url") or entry.get("source_url"),
                         fetched_at=row.get("fetched_at") or None,
                         retained_sha256=entry["sha256"], upstream_raw_sha256=row.get("sha256") or None,
                         upstream_hash_status="RECORDED_IN_RETAINED_MANIFEST_NOT_REVALIDATED")


def _city_rows(capture: _Capture, processed: Path) -> tuple[dict, list[str]]:
    path = processed / "tc_company_by_industry_monthly.csv"
    result: dict[str, int | None] = {}
    problems: list[str] = []
    if not path.exists():
        return result, ["GQ_CITY_SOURCE_MISSING"]
    try:
        rows = capture.csv(path, "gcis_city_aggregate", CITY_URL)
        if rows and not {"year_month", "industry", "metric", "companies"}.issubset(rows[0]):
            return {}, ["GQ_CITY_SCHEMA_INVALID"]
        for row in rows:
            if row.get("industry", "").strip() not in CITY_INDUSTRIES or row.get("metric") != "new":
                continue
            month = row.get("year_month", "")
            if not MONTH_RE.fullmatch(month):
                problems.append("GQ_CITY_PERIOD_INVALID")
                continue
            value = _integer(row.get("companies"))
            if month in result:  # Even matching duplicate keys fail this observation.
                result[month] = None
                problems.append("GQ_CITY_DUPLICATE_PERIOD")
            else:
                result[month] = value
    except (OSError, ValueError, csv.Error):
        return {}, ["GQ_CITY_SOURCE_UNREADABLE"]
    return result, sorted(set(problems))


def _classification(capture: _Capture, raw: Path, injected: dict | None) -> tuple[dict, dict]:
    labels: dict[str, dict] = {}
    meta = {"available": False, "reason_codes": [], "current_label_retrospective": True}
    if injected is not None:
        for company, entry in injected.items():
            value = {"industry_code": entry} if isinstance(entry, str) else dict(entry)
            labels[str(company)] = {
                "industry_code": str(value.get("industry_code", "")),
                "basis": value.get("basis", "INJECTED_MAPPING"),
                "label_as_of": value.get("label_as_of"),
                "historical": bool(value.get("historical", False)),
            }
        meta.update(available=True, mapping_version=_digest(injected), injected_mapping=True)
        return labels, meta

    tax_path = raw / "tax_registry" / "bgmopen1_industry.csv"
    if tax_path.exists():
        try:
            groups: dict[str, set[str]] = defaultdict(set)
            for row in capture.csv(tax_path, "gcis_tax_classification", "https://eip.fia.gov.tw/data/BGMOPEN1.zip"):
                code = str(row.get("行業代號", "")).strip()
                company = str(row.get("統一編號", "")).strip()
                if re.fullmatch(r"\d{8}", company) and re.fullmatch(r"\d{6}", code):
                    groups[company].add(code[:2])
            for company, codes in groups.items():
                labels[company] = {"industry_code": next(iter(codes)) if len(codes) == 1 else None,
                                   "basis": "TAX_PRIMARY_INDUSTRY", "historical": False,
                                   "ambiguous": len(codes) != 1, "label_as_of": None}
            meta["available"] = True
        except (OSError, ValueError, csv.Error):
            meta["reason_codes"].append("GQ_TAX_CLASSIFICATION_UNREADABLE")

    company_path = raw / "gcis_api_cache" / "company_items.jsonl"
    items_path = raw / "gcis_api_cache" / "item_dgbas.json"
    # A C-prefixed business item is not a manufacturing division code. Without
    # the official mapping, there is intentionally no prefix-guessing fallback.
    if company_path.exists() and items_path.exists():
        try:
            item_map = json.loads(capture.read(items_path, "gcis_item_classification").decode("utf-8-sig"))
            records: dict[str, dict] = {}
            for line in capture.read(company_path, "gcis_company_classification").decode("utf-8-sig").splitlines():
                if line.strip():
                    record = json.loads(line)
                    records[str(record.get("id", ""))] = record
            for company, record in records.items():
                if company in labels or not record.get("items"):
                    continue
                values = item_map.get(record["items"][0], [])
                values = [values] if isinstance(values, str) else values
                codes = {str(code)[:2] for code in values if re.fullmatch(r"\d{4,6}", str(code))}
                labels[company] = {"industry_code": next(iter(codes)) if len(codes) == 1 else None,
                                   "basis": "CURRENT_API_ITEM", "historical": False,
                                   "ambiguous": len(codes) > 1, "label_as_of": record.get("fetched_at")}
            meta["available"] = True
        except (OSError, ValueError, TypeError):
            meta["reason_codes"].append("GQ_API_CLASSIFICATION_UNREADABLE")
    if not meta["available"]:
        meta["reason_codes"].append("GQ_CLASSIFICATION_UNAVAILABLE")
    meta["mapping_version"] = _digest([entry for entry in capture.manifest if "classification" in entry["source_id"]])
    return labels, meta


def _registry(capture: _Capture, raw: Path, cutoff: str, window_start: str,
              include_prior: bool = True, list_cutoff: str | None = None) -> tuple[list[dict], dict, dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    # Keep the requested window plus each changed company's immediately prior
    # state. Materialising every historical event costs hundreds of MB and is
    # unnecessary for a three-month report. All scanned source bytes remain
    # hashed, and all monthly parse states are retained for continuity checks.
    prior_states: dict[str, tuple[str, list[tuple[tuple, dict]]]] = {}
    files: dict[str, dict[str, str]] = {kind: {} for kind in LIST_IDS}
    diagnostics: Counter = Counter()
    list_root = raw / "gcis_lists"
    for kind, dataset in LIST_IDS.items():
        for path in sorted((list_root / kind).glob("*.csv")):
            month = path.stem
            if not MONTH_RE.fullmatch(month):
                continue
            diagnostics["available_raw_file_count"] += 1
            if list_cutoff is not None and month > list_cutoff:
                diagnostics["excluded_future_list_files"] += 1
                continue
            # Without any reviewable industry classification, a historical
            # capital chain cannot contribute a local result. Capture the
            # window (and later retained lists for late observations) only;
            # do not load 13 years of unrelated confidential registry rows.
            if not include_prior and month < window_start:
                continue
            url = f"https://data.gcis.nat.gov.tw/od/detail?oid={dataset}"
            try:
                rows = capture.csv(path, "gcis_list_" + kind, url)
                required = {"統一編號", "公司所在地", "資本額", DATE_COLUMNS[kind]}
                header = next(csv.reader(io.StringIO(_decode(capture.read(path, "gcis_list_" + kind))), strict=True), [])
                if not required.issubset(header):
                    files[kind][month] = "INVALID_SCHEMA"
                    continue
                files[kind][month] = "PARSED"
                diagnostics["raw_file_count"] += 1
                resolved_file = str(path.resolve())
                for index, row in enumerate(rows, 2):
                    if None in row:
                        diagnostics["invalid_event_rows"] += 1
                        files[kind][month] = "PARSED_WITH_INVALID_ROWS"
                        continue
                    company = str(row.get("統一編號", "")).strip()
                    event_date = _event_date(row.get(DATE_COLUMNS[kind], ""))
                    if not re.fullmatch(r"\d{8}", company) or not event_date:
                        diagnostics["invalid_event_rows"] += 1
                        files[kind][month] = "PARSED_WITH_INVALID_ROWS"
                        continue
                    if event_date[:7] > cutoff:
                        continue
                    before_window = event_date[:7] < window_start
                    if before_window:
                        if kind == "dissolved":
                            continue
                        prior_day = prior_states.get(company, ("", []))[0]
                        if event_date < prior_day:
                            continue
                    address = str(row.get("公司所在地", "")).strip().replace("台中市", "臺中市", 1)
                    match = re.match(r"^臺中市([^市縣鄉鎮區]{1,4}區)", address)
                    # Keep district unknowns in the sample denominator.
                    district = match.group(1) if match else None
                    if not address.startswith("臺中市"):
                        diagnostics["non_taichung_rows"] += 1
                        continue
                    amount = _integer(row.get("資本額"))
                    basis = str(row.get("資本額口徑") or "REGISTERED_CAPITAL")
                    currency = str(row.get("幣別") or "TWD")
                    observation = {"company_id": company, "kind": kind, "event_date": event_date,
                                   "district": district, "capital": amount, "capital_basis": basis,
                                   "currency": currency, "list_month": month,
                                   "source_row_ref": [resolved_file, index],
                                   "address_digest": hashlib.sha256(address.encode("utf-8")).hexdigest()}
                    approval = str(row.get("核准文號") or row.get("登記事件識別碼") or "").strip()
                    key = (company, kind, approval or event_date)
                    if before_window:
                        prior_day, prior = prior_states.get(company, ("", []))
                        if event_date > prior_day:
                            prior = []
                        prior.append((key, observation))
                        prior_states[company] = (event_date, prior)
                    else:
                        groups[key].append(observation)
            except (OSError, ValueError, UnicodeError, csv.Error):
                files[kind][month] = "UNREADABLE"
                diagnostics["unreadable_files"] += 1

    needed_baselines = {key[0] for key in groups if key[1] == "change"}
    for company in needed_baselines:
        for key, observation in prior_states.get(company, ("", []))[1]:
            groups[key].append(observation)
    diagnostics["baseline_company_count"] = len(needed_baselines)
    canonical = []
    for key, observations in groups.items():
        variants = {(row["event_date"], row["district"], row["capital"], row["capital_basis"], row["currency"], row["address_digest"])
                    for row in observations}
        item = dict(observations[0])
        item.update(event_id=_digest(key), status="VALID" if len(variants) == 1 else "CONFLICT",
                    observation_refs=sorted(_digest(row["source_row_ref"]) for row in observations))
        diagnostics["duplicate_observations_collapsed"] += len(observations) - 1 if len(variants) == 1 else 0
        diagnostics["conflict_events"] += int(len(variants) != 1)
        canonical.append(item)
    diagnostics["canonical_event_count"] = len(canonical)
    diagnostics["canonical_scope"] = "LOCAL_WINDOW_AND_REQUIRED_PRIOR_STATES"
    return canonical, files, dict(diagnostics)


def _capital_events(events: list[dict], files: dict) -> tuple[list[dict], Counter]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        if event["kind"] in {"setup", "change"}:
            grouped[event["company_id"]].append(event)
    result, issues = [], Counter()
    for rows in grouped.values():
        by_date: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_date[row["event_date"]].append(row)
        previous = None
        for day, observations in sorted(by_date.items()):
            # An unresolved state breaks continuity; never bridge through it.
            if len(observations) != 1 or observations[0]["status"] != "VALID":
                previous = None
                issues["CAPITAL_CHAIN_CONFLICT"] += 1
                continue
            row = observations[0]
            if row["capital"] is None:
                previous = None
                issues["CAPITAL_VALUE_UNKNOWN"] += 1
                continue
            if row["kind"] == "change":
                if previous is None:
                    issues["BASELINE_UNKNOWN"] += 1
                elif (row["capital_basis"], row["currency"]) != (previous["capital_basis"], previous["currency"]):
                    issues["CAPITAL_BASIS_CHANGED"] += 1
                elif row["capital"] > previous["capital"]:
                    continuity = all(files["change"].get(month) == "PARSED"
                                     for month in _months(previous["event_date"][:7], day[:7]))
                    precision = "ADJACENT_RETAINED_STATES" if continuity else "GAPPED_STATE_COMPARISON"
                    result.append({**row, "baseline_date": previous["event_date"],
                                   "capital_delta": row["capital"] - previous["capital"],
                                   "event_precision": precision,
                                   "capital_source_refs": previous["observation_refs"] + row["observation_refs"]})
            previous = row
    return result, issues


def _legacy(capture: _Capture, processed: Path, start: str, end: str, districts: list[str], division: str) -> list[dict]:
    path = processed / "tc_mfg_company_events_monthly.csv"
    if not path.exists():
        return []
    try:
        rows = capture.csv(path, "gcis_legacy_classified_aggregate")
        return [{"year_month": row["year_month"], "district": row["district"],
                 "industry_code": division, "event": row.get("event"),
                 "legacy_assigned_company_count": _integer(row.get("companies")),
                 "population_scope": "CLASSIFIED_EVENT_SAMPLE", "qualification": "PARTIAL",
                 "reason_codes": ["GQ_LEGACY_AGGREGATE_ONLY", "GQ_ROW_LINEAGE_UNAVAILABLE"],
                 "usable_for_official_local_count": False}
                for row in rows if start <= row.get("year_month", "") <= end
                and row.get("district") in districts and row.get("industry_code") == division]
    except (OSError, ValueError, csv.Error):
        return []


def capture_gcis_context(scenario: dict, *, processed_dir=None, raw_dir=None,
                         classification_map: dict | None = None) -> dict:
    """Capture current local bytes; historical mode is retrospective, never as-of.

    ``classification_map`` is a trusted, injectable mapping for isolated tests or
    adapters with an already reviewed mapping. Its digest and injected status are
    included in evidence. A user-facing request must not supply this parameter.
    """
    processed, raw = Path(processed_dir or BASE / "data/processed"), Path(raw_dir or BASE / "data/raw")
    observation = scenario.get("observation", {})
    if observation.get("knowledge_cutoff") is not None:
        raise ValueError("HISTORICAL_VINTAGE_NOT_AVAILABLE")
    mode = observation.get("mode", "LATEST_AVAILABLE")
    if mode not in {"LATEST_AVAILABLE", "FIXED_MONTH"}:
        raise ValueError("Unsupported observation mode")
    window = observation.get("window_months", 3)
    if window not in {3, 6, 12}:
        raise ValueError("GCIS local window must be 3, 6, or 12 months")
    division = str(scenario.get("manufacturing", {}).get("division_code", scenario.get("manufacturing_division", "29")))
    if not re.fullmatch(r"\d{2}", division) or not 8 <= int(division) <= 34:
        raise ValueError("Invalid manufacturing division")
    districts = list(dict.fromkeys(scenario.get("districts", [])))
    capture = _Capture()
    city_values, city_problems = _city_rows(capture, processed)
    source_months = [path.stem for kind in LIST_IDS for path in (raw / "gcis_lists" / kind).glob("*.csv")
                     if MONTH_RE.fullmatch(path.stem)]
    if mode == "FIXED_MONTH":
        cutoff = observation.get("month", "")
        if not isinstance(cutoff, str) or not MONTH_RE.fullmatch(cutoff):
            raise ValueError("FIXED_MONTH requires a valid month")
    else:
        current_month = _current_month()
        candidates = [month for month in list(city_values) + source_months if month <= current_month]
        cutoff = max(candidates) if candidates else current_month
        if any(month > current_month for month in city_values):
            city_problems.append("GQ_FUTURE_OBSERVATION_EXCLUDED")

    city_end = max((month for month in city_values if month <= cutoff), default=cutoff)
    current_start, baseline_end = _month_shift(city_end, -11), _month_shift(city_end, -12)
    baseline_start = _month_shift(city_end, -23)
    city_window = _months(baseline_start, city_end)
    missing_city = [month for month in city_window if city_values.get(month) is None]
    city_available = not missing_city and bool(city_values)
    current_sum = sum(city_values[month] for month in _months(current_start, city_end)) if city_available else None
    baseline_sum = sum(city_values[month] for month in _months(baseline_start, baseline_end)) if city_available else None
    city_evidence = {
        "evidence_id": "ev_gcis_city_" + _digest([city_end, capture.manifest])[:16],
        "source_name": "經濟部GCIS公司登記新設家數按行業別及縣市別統計", "source_url": CITY_URL,
        "population_scope": "OFFICIAL_CITY_AGGREGATE", "geography": "臺中全市", "industry": "製造業大類",
        "period_start": baseline_start, "period_end": city_end, "missing_months": missing_city,
        "source_ids": ["gcis_city_aggregate"], "purpose": "WITHIN_SERIES_CHANGE",
        "qualification": "QUALIFIED" if city_available else "UNAVAILABLE",
        "reason_codes": city_problems + (["GQ_CITY_WINDOW_INCOMPLETE"] if missing_city else []),
        "limitations": ["全市公司新設不是區域職缺或缺工人數。", "回看觀測期使用本次留存版本，不重現當時可知資訊。"],
    }
    city = {"available": city_available, "start": current_start, "end": city_end,
            "current_sum": current_sum, "baseline_start": baseline_start, "baseline_end": baseline_end,
            "baseline_sum": baseline_sum,
            "change_pct": round((current_sum - baseline_sum) * 100 / baseline_sum, 4) if city_available and baseline_sum else None,
            "monthly_rows": [{"year_month": month, "new_company_count": city_values.get(month)} for month in city_window],
            "evidence": city_evidence}

    local_end = cutoff
    if mode == "LATEST_AVAILABLE":
        common = set.intersection(*(set(path.stem for path in (raw / "gcis_lists" / kind).glob("*.csv")
                                            if MONTH_RE.fullmatch(path.stem) and path.stem <= cutoff) for kind in LIST_IDS))
        if common:
            local_end = max(common)
    local_start = _month_shift(local_end, 1 - window)
    labels, classification_meta = _classification(capture, raw, classification_map)
    events, files, diagnostics = _registry(capture, raw, cutoff, local_start,
                                          include_prior=classification_meta["available"],
                                          list_cutoff=_current_month())
    capital, capital_issues = _capital_events(events, files)
    window_capital_unknown = _unknown_capital_ids(events, files, local_start, local_end)
    findings, actions = [], []

    def finding(rule: str, district: str | None, reason: str):
        item = {"rule_id": rule, "district": district, "reason_code": reason}
        if item not in findings:
            findings.append(item)

    def action(action_id: str, rule: str, district: str | None, label: str, reason: str):
        actions.append({"action_id": action_id, "rule_id": rule, "district": district, "label": label, "reason": reason})

    if city_available:
        if current_sum > baseline_sum:
            finding("GS01_CITY_NEW_UP", None, "CITY_NEW_ACTIVITY_INCREASED")
            action("CHECK_RELATED_JOB_CHANNELS", "GS01_CITY_NEW_UP", None, "確認相關職類的徵才動向", "全市新設活動增加；需另查職缺，不能直接推論缺工。")
        elif current_sum < baseline_sum:
            finding("GS02_CITY_NEW_DOWN", None, "CITY_NEW_ACTIVITY_DECREASED")
    else:
        finding("GS07_SOURCE_UNAVAILABLE", None, "GQ_CITY_WINDOW_INCOMPLETE")
        action("RECOVER_CITY_SOURCE", "GS07_SOURCE_UNAVAILABLE", None, "補齊全市統計比較窗口", "24個月份不完整，暫不判斷全市新設方向。")

    local = []
    all_local_events = [row for row in events if local_start <= row["event_date"][:7] <= local_end]
    for district in districts:
        reasons = {"GQ_CLASSIFIED_SAMPLE_NOT_POPULATION"}
        if not classification_meta["available"]:
            reasons.add("GQ_CLASSIFICATION_UNAVAILABLE")
        counts, coverage, kind_status = {}, {}, {}
        for kind, output_name in (("setup", "new_company_count"), ("change", "capital_increase_company_count"),
                                  ("dissolved", "dissolved_company_count")):
            window_months = _months(local_start, local_end)
            missing = [month for month in window_months if files[kind].get(month) != "PARSED"]
            candidates = [row for row in all_local_events if row["kind"] == kind]
            valid = [row for row in candidates if row["status"] == "VALID"]
            classified = [row for row in valid if labels.get(row["company_id"], {}).get("industry_code")]
            conflicts = [row for row in candidates if row["status"] != "VALID"]
            target = [row for row in classified if row["district"] == district
                      and labels[row["company_id"]]["industry_code"] == division]
            if any(not labels[row["company_id"]].get("historical") for row in classified):
                reasons.add("GQ_CURRENT_LABEL_RETROSPECTIVE")
            if len(classified) < len(valid):
                reasons.add("GQ_CLASSIFICATION_INCOMPLETE")
            if any(row["district"] is None for row in valid):
                reasons.add("GQ_DISTRICT_UNRESOLVED")
            if conflicts:
                reasons.add("GQ_EVENT_CONFLICT")
            if missing:
                reasons.add("GQ_LOCAL_SOURCE_INCOMPLETE")
            # A complete source with no events is a defined empty sample; no
            # source or no usable classification is unknown, never sample zero.
            usable = not missing and not conflicts and (bool(classified) or not valid)
            if kind == "change":
                capital_target = [row for row in capital if local_start <= row["event_date"][:7] <= local_end
                                  and row["district"] == district
                                  and labels.get(row["company_id"], {}).get("industry_code") == division]
                exact = [row for row in capital_target if row["event_precision"] == "ADJACENT_RETAINED_STATES"]
                # Baseline availability is assessed below per change, not by
                # treating all non-increasing changes as unknown increases.
                target_ids = {row["event_id"] for row in target}
                if target_ids & window_capital_unknown or len(exact) != len(capital_target):
                    usable = False
                    reasons.add("GQ_CAPITAL_BASELINE_OR_CONTINUITY_UNKNOWN")
                value = len({row["company_id"] for row in exact}) if usable else None
            else:
                value = len({row["company_id"] for row in target}) if usable else None
            counts[output_name] = value
            kind_status[kind] = {"available": usable, "missing_or_invalid_months": missing,
                                 "value_status": "UNKNOWN" if value is None else "SAMPLE_MATCH_ZERO" if value == 0 else "EXACT_WITHIN_SCOPE"}
            coverage[kind] = {"denominator_scope": "臺中全市清冊同事件觀察窗，不是指定區域中類完整率",
                              "source_events": len(candidates), "valid_events": len(valid),
                              "classified_events": len(classified), "unknown_classification_events": len(valid) - len(classified),
                              "conflict_events": len(conflicts),
                              "classification_ratio": len(classified) / len(valid) if valid else None}

        available = any(value is not None for value in counts.values())
        evidence = {"evidence_id": "ev_gcis_local_" + _digest([district, division, local_start, local_end, classification_meta])[:16],
                    "population_scope": "CLASSIFIED_EVENT_SAMPLE", "purpose": "POINT_DESCRIPTION",
                    "geography": district, "industry_code": division, "period_start": local_start, "period_end": local_end,
                    "qualification": "PARTIAL" if available else "UNAVAILABLE", "comparison_status": "DESCRIPTIVE_ONLY",
                    "reason_codes": sorted(reasons), "coverage": coverage, "per_event_status": kind_status,
                    "classification": classification_meta, "canonical_diagnostics": diagnostics,
                    "capital_diagnostics": dict(capital_issues), "source_ids": ["gcis_list_setup", "gcis_list_change", "gcis_list_dissolved"],
                    "capital_state_observations": [
                        {"event_id": row["event_id"], "baseline_date": row["baseline_date"],
                         "current_state_date": row["event_date"], "capital_delta_twd": row["capital_delta"],
                         "event_precision": row["event_precision"], "source_row_refs": row["capital_source_refs"]}
                        for row in capital if local_start <= row["event_date"][:7] <= local_end
                        and row["district"] == district
                        and labels.get(row["company_id"], {}).get("industry_code") == division],
                    "limitations": ["數字僅為本次規則成功分類的觀察樣本，不是區域製造業母體或其下限。",
                                    "核准月與清冊月不同；本次回看使用目前留存版本。",
                                    "公司登記地址不是工廠或職缺工作地點；不推論缺工或招募成敗。"]}
        local.append({"district": district, "industry_code": division, "start": local_start, "end": local_end,
                      "available": available, **counts, "qualification": evidence["qualification"],
                      "reason_codes": sorted(reasons), "evidence": evidence})
        finding("GS04_LOCAL_PARTIAL", district, "GQ_CLASSIFIED_SAMPLE_NOT_POPULATION")
        finding("GS06_NET_BLOCKED", district, "GQ_NET_CHANGE_NOT_ENABLED")
        if any(value and value > 0 for value in counts.values()):
            finding("GS03_LOCAL_ACTIVITY", district, "CLASSIFIED_LOCAL_ACTIVITY_OBSERVED")
            action("CHECK_RELATED_JOB_CHANNELS", "GS03_LOCAL_ACTIVITY", district, "查證同職類公開徵才", "已分類公司活動只提供查證線索，不代表新增職缺。")
        if any(value == 0 for value in counts.values() if value is not None):
            finding("GS05_SAMPLE_ZERO", district, "CLASSIFIED_SAMPLE_MATCH_ZERO")
        if (not available or "GQ_LOCAL_SOURCE_INCOMPLETE" in reasons or "GQ_EVENT_CONFLICT" in reasons
                or "GQ_CLASSIFICATION_UNAVAILABLE" in reasons):
            finding("GS07_SOURCE_UNAVAILABLE", district, "GQ_LOCAL_SOURCE_OR_CLASSIFICATION_UNAVAILABLE")
            action("RECOVER_LOCAL_CLASSIFICATION", "GS07_SOURCE_UNAVAILABLE", district, "補齊清冊與分類證據", "資料不足的指標保持未知，不能據此判定同業活動為零。")
        finding("GS08_SCOPE_DIFFERENCE", district, "CITY_AND_LOCAL_SCOPES_DIFFER")

    legacy = _legacy(capture, processed, local_start, local_end, districts, division)
    _attach_provenance(capture, raw)
    release = _digest({"sources": capture.manifest, "rules": RULES_VERSION, "classification": classification_meta})
    for evidence in [city_evidence] + [item["evidence"] for item in local]:
        evidence["source_release"] = release
        evidence["rules_version"] = RULES_VERSION
    actions.sort(key=lambda item: (0 if item["rule_id"] == "GS07_SOURCE_UNAVAILABLE" else 1,
                                   districts.index(item["district"]) if item["district"] in districts else -1,
                                   item["rule_id"]))
    return {"available": city_available or any(item["available"] for item in local), "city": city, "local": local,
            "findings": findings, "next_actions": actions, "evidence": [city_evidence] + [item["evidence"] for item in local],
            "source_manifest": capture.manifest, "cutoff_month": cutoff, "source_release": release,
            "local_observation_window": {"start": local_start, "end": local_end},
            "city_background_comparison_windows": {"current_start": current_start, "current_end": city_end,
                                                   "baseline_start": baseline_start, "baseline_end": baseline_end},
            "historical_mode": "RETROSPECTIVE_CURRENT_RETAINED_VERSION", "knowledge_cutoff": None,
            "legacy_observations": legacy, "diagnostics": diagnostics}


def _unknown_capital_ids(events: list[dict], files: dict, start: str, end: str) -> set[str]:
    """Find changes whose increase/non-increase cannot be established exactly."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in events:
        if row["kind"] in {"setup", "change"}:
            grouped[row["company_id"]].append(row)
    unknown = set()
    for rows in grouped.values():
        previous = None
        dates = Counter(row["event_date"] for row in rows)
        for row in sorted(rows, key=lambda item: item["event_date"]):
            valid = row["status"] == "VALID" and row["capital"] is not None and dates[row["event_date"]] == 1
            if row["kind"] == "change" and start <= row["event_date"][:7] <= end:
                comparable = valid and previous is not None and previous["event_date"] < row["event_date"]
                comparable = comparable and (row["capital_basis"], row["currency"]) == (previous["capital_basis"], previous["currency"])
                comparable = comparable and all(files["change"].get(month) == "PARSED"
                                                for month in _months(previous["event_date"][:7], row["event_date"][:7]))
                if not comparable:
                    unknown.add(row["event_id"])
            previous = row if valid else None
    return unknown
