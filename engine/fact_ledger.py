"""Typed, snapshot-bound facts for the official comparison report.

These contracts establish consistency with retained, approved inputs, not the
truth or completeness of the outside world. No LLM-created facts are accepted.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

VERSION = "report-facts-v1"
METRICS = {
    "jobs.vacancy_postings": ("刊登職缺", "posting", "COUNT", "PUBLIC_JOB_OBSERVATIONS"),
    "jobs.requested_workers": ("刊登需求人數", "person", "COUNT", "PUBLIC_JOB_OBSERVATIONS"),
    "jobs.distinct_company_names": ("不同公司名稱數", "company_name", "COUNT", "PUBLIC_JOB_OBSERVATIONS"),
    "gcis.city_new_companies": ("全市新設公司", "company", "COUNT", "GCIS_CONTEXT"),
    "gcis.local_new_companies": ("已分類樣本新設公司", "company", "COUNT", "GCIS_CONTEXT"),
    "gcis.local_capital_increase_companies": ("已分類樣本相鄰狀態資本增加公司", "company", "COUNT", "GCIS_CONTEXT"),
    "gcis.local_dissolved_companies": ("已分類樣本解散公司", "company", "COUNT", "GCIS_CONTEXT"),
    "plan.monthly_net_hires": ("你的每月淨到職目標", "person", "COUNT", "HIRING_PLAN"),
    "wage.average_insured_salary": ("全市製造業產業勞工（參加就保口徑）平均投保薪資", "TWD", "DECIMAL", "COMMON_BACKGROUND"),
    "factory.registered_factories": ("登記工廠", "factory", "COUNT", "COMMON_BACKGROUND"),
}
DISCLOSURES = {
    "CONSISTENCY_SCOPE": "本報告只核對與核准快照及規則的一致性，不保證來源無誤、涵蓋全市場或存在因果關係。",
    "PUBLIC_SNAPSHOT_NOT_SHORTAGE": "這是官方公開刊登樣本，不是實際缺工人數、全部雇主或招聘成功率。",
    "OCCUPATION_PROXY": "職類以職務文字檢索；製造中類用於公司事件，不代表這些職缺雇主屬該正式行業。",
    "COMPANY_NAMES_NOT_ENTITIES": "公司名稱去重不等於已依統編核實的法人企業家數。",
    "QUERY_LIMIT_REACHED": "至少一個選區達查詢上限；各值是可觀測下限，整列不作全區排名。",
    "JOBS_UNAVAILABLE": "職缺快照或所選行政區稽核不足，不能將沒有資料當成零或產生排名。",
    "CITY_NOT_DISTRICT": "全市行業大類背景不能下推為行政區或較細中類的數值，也不等於招募需求。",
    "GCIS_LOCAL_SAMPLE": "區域公司事件只是可分類的登記樣本；公司登記地不等於工廠或工作地。目前不作跨區或跨期排名。",
    "GCIS_PARTIAL": "區域來源、分類或前後狀態不完整；只描述有證據的樣本，不補零、不推論淨增或缺工。",
    "GCIS_UNAVAILABLE": "同業公司事件證據不足；需要補齊來源及分類資料，不能解讀為沒有同業活動。",
    "NET_CHANGE_BLOCKED": "目前不以新設減解散推論企業存量淨增，也不推論企業事件造成招聘或缺工。",
    "USER_PLAN_NOT_FORECAST": "這是你的淨到職目標，不是官方觀測或預測可招到的人數；未估離職替補、招募漏斗及到職延遲。",
    "INSURED_NOT_TAKE_HOME": "平均投保薪資不是實領薪資、職缺開薪或薪資中位數。",
    "FACTORY_NOT_HIRING": "工廠登記家數不是企業總數、職缺、缺工或擴廠計畫。",
    "CAUSE_UNKNOWN": "現有資料只能描述觀察差異，沒有證據判定其原因或保證單一企業能招到人。",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{digest(value)[:24]}"


def normal_keyword(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def valid_period(value: str) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", value):
        return False
    try:
        date.fromisoformat(value if len(value) == 10 else value + "-01")
        return True
    except ValueError:
        return False


def amount(value: Any, *, count: bool = False) -> str:
    if isinstance(value, bool) or value is None:
        raise ValueError("INVALID_QUANTITY")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("INVALID_QUANTITY") from None
    if not numeric.is_finite() or (count and (numeric < 0 or numeric != numeric.to_integral_value())):
        raise ValueError("INVALID_QUANTITY")
    return str(int(numeric)) if count else format(numeric, "f")


def quality(population: str, *, available=True, capped=False, partial=False, zero_sample=False, reasons=()) -> dict:
    return {
        "purpose": "POINT_DESCRIPTION", "population_scope": population,
        "qualification": "UNAVAILABLE" if not available else "PARTIAL" if partial or capped else "QUALIFIED",
        "value_status": "UNKNOWN" if not available else "LOWER_BOUND" if capped else "SAMPLE_MATCH_ZERO" if zero_sample else "EXACT_WITHIN_SCOPE",
        "comparison_status": "NOT_COMPARABLE" if not available else "DESCRIPTIVE_ONLY" if partial or capped or population == "CLASSIFIED_EVENT_SAMPLE" else "COMPARABLE_SAMPLE",
        "classification_denominator_scope": None, "classification_ratio": None,
        "reason_codes": list(reasons),
    }


def approved_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and (host.endswith(".gov.tw") or host == "taiwanjobs.gov.tw") and not parsed.username
    except (ValueError, TypeError):
        return False


class FactLedger:
    def __init__(self, report_id: str, manifest: dict):
        self.report_id = report_id
        self.manifest_hash = manifest.get("manifest_hash") or digest(manifest)
        if not re.fullmatch(r"[a-f0-9]{64}", self.manifest_hash):
            raise ValueError("INVALID_MANIFEST_HASH")
        self.facts: list[dict] = []
        self.evidence: list[dict] = []
        self.filter_registry: dict[str, dict] = {}

    def filter(self, spec: dict) -> dict:
        """Registry retains the complete expression; a digest alone is not enough."""
        spec = json.loads(canonical_json(spec))
        hash_value = digest(spec)
        key = "filter_" + hash_value[:24]
        self.filter_registry[key] = {"filter_spec_id": key, "filter_digest": hash_value, "spec": spec,
                                     "canonicalization": "UTF-8 JSON: sorted keys, compact separators; arrays retain order"}
        return {"filter_spec_id": key, "filter_digest": hash_value}

    def evidence_for(self, source: str, payload: Any, evidence: Any = None) -> str:
        evidence = evidence if isinstance(evidence, dict) else {}
        defaults = {
            "jobs": ("44062", "勞動部台灣就業通公開職缺", "https://data.gov.tw/dataset/44062"),
            "gcis": ("GCIS", "經濟部商工行政資料", "https://data.gcis.nat.gov.tw/od/"),
            "wage": ("100999", "勞工保險局平均投保薪資", "https://data.gov.tw/dataset/100999"),
            "factory": ("174209", "臺中市工廠登記", "https://data.gov.tw/dataset/174209"),
            "plan": ("USER_CONFIRMED_SCENARIO", "使用者確認的招募規劃", None),
        }
        if source not in defaults:
            raise ValueError("UNAPPROVED_SOURCE")
        dataset, label, url = defaults[source]
        urls = evidence.get("source_urls") or [evidence.get("source_url")]
        urls = [v for v in urls if isinstance(v, str) and approved_url(v)]
        item = {
            "report_id": self.report_id, "dataset_id": dataset,
            "snapshot_id": str(evidence.get("snapshot_id") or evidence.get("data_period") or "retained-report-input"),
            "source_name": label, "source_url": urls[0] if urls else url,
            "retained_artifact_hash": digest(payload), "manifest_hash": self.manifest_hash,
            "row_locator": {"payload_hash": digest(payload)},
            "transformation_rule": VERSION, "fetched_at": evidence.get("last_updated") or evidence.get("fetched_at"),
            "source_published_at": evidence.get("source_published_at"),
            # Only adapters call this method. Preserve their structured audit
            # trail for evidence drawers/exports; models never supply Evidence.
            # Consumers render these values as text, never executable markup.
            "source_details": json.loads(canonical_json(evidence)),
        }
        for key in ("source_release", "classification", "qualification", "reason_codes", "coverage", "per_event_status",
                    "canonical_diagnostics", "capital_diagnostics", "capital_state_observations", "source_row_refs", "limitations"):
            if key in evidence:
                item[key] = json.loads(canonical_json(evidence[key]))
        if isinstance(evidence.get("row_locator"), dict):
            item["row_locator"].update(json.loads(canonical_json(evidence["row_locator"])))
        item["evidence_id"] = stable_id("ev", item)
        if item["evidence_id"] not in {e["evidence_id"] for e in self.evidence}:
            self.evidence.append(item)
        return item["evidence_id"]

    def add(self, metric_id: str, value: Any, *, district: str | None, start: str, end: str | None = None,
            period_kind="SNAPSHOT", role="WORK_LOCATION", selection: dict, population="PUBLISHED_VACANCIES",
            data_kind="OBSERVED", evidence_ids: list[str], point_quality: dict | None = None) -> dict:
        if metric_id not in METRICS or data_kind not in {"OBSERVED", "DERIVED", "USER_PLAN"}:
            raise ValueError("UNAPPROVED_METRIC_OR_DATA_KIND")
        if not valid_period(start) or not valid_period(end or start) or (end or start) < start:
            raise ValueError("INVALID_FACT_PERIOD")
        label, unit, kind, _ = METRICS[metric_id]
        numeric = amount(value, count=kind == "COUNT") if value is not None else None
        if numeric is not None and metric_id == "wage.average_insured_salary" and Decimal(numeric) < 0:
            raise ValueError("NEGATIVE_WAGE")
        q = point_quality or quality(population, available=value is not None)
        if (q["value_status"] == "UNKNOWN") != (numeric is None):
            raise ValueError("UNKNOWN_VALUE_CONFLICT")
        known_evidence = {e["evidence_id"] for e in self.evidence}
        if not evidence_ids or not set(evidence_ids) <= known_evidence:
            raise ValueError("UNKNOWN_EVIDENCE")
        if selection.get("filter_spec_id") not in self.filter_registry or selection.get("filter_digest") != self.filter_registry[selection["filter_spec_id"]]["filter_digest"]:
            raise ValueError("UNKNOWN_FILTER")
        fact = {"report_id": self.report_id, "manifest_hash": self.manifest_hash, "metric_id": metric_id,
                "value": {"kind": kind if numeric is not None else "UNKNOWN", "amount": numeric, "lower": None, "upper": None},
                "unit": unit, "subject": {"city": "臺中市", "district": district, "geography_role": role},
                "period": {"kind": period_kind, "start": start, "end": end or start, "calendar": "GREGORIAN_NORMALIZED"},
                "selection": selection, "data_kind": data_kind, "quality": q, "evidence_ids": evidence_ids}
        fact["fact_id"] = stable_id("f", fact)
        self.facts.append(fact)
        return fact


def comparable(left: dict, right: dict) -> bool:
    return (
        left["metric_id"] == right["metric_id"] and left["unit"] == right["unit"]
        and left["period"] == right["period"] and left["selection"] == right["selection"]
        and left["report_id"] == right["report_id"] and left["manifest_hash"] == right["manifest_hash"]
        and left["subject"]["geography_role"] == right["subject"]["geography_role"] == "WORK_LOCATION"
        and left["subject"]["district"] != right["subject"]["district"]
        and left["data_kind"] == right["data_kind"] == "OBSERVED"
        and all(f["quality"]["comparison_status"] == "COMPARABLE_SAMPLE" and f["quality"]["population_scope"] == "PUBLISHED_VACANCIES"
                and f["value"]["kind"] == "COUNT" for f in (left, right))
    )
