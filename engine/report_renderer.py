"""Strict plan validation and one renderer for report pages, Q&A and exports."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path

from engine.fact_ledger import DISCLOSURES, METRICS, comparable, digest, stable_id

TEMPLATE_VERSION = "report-renderer-v1"
HEADINGS = {
    "PUBLIC_JOB_OBSERVATIONS": "公開職務刊登", "GCIS_CONTEXT": "同業公司事件與全市背景",
    "COMMON_BACKGROUND": "共同背景", "HIRING_PLAN": "你的招募規劃",
    "EVIDENCE_GAPS": "證據與限制", "NEXT_STEPS": "下一步查證",
}


class PlanValidationError(ValueError):
    """A safe code only; never echoes untrusted model text."""


def current_render_contract_hash():
    """Bind retained catalogs to code and registries, not just a version label.

    No cache: changed registry values or deployed source must invalidate old
    report Q&A even when somebody forgot to increment TEMPLATE_VERSION. Reading
    an old report/export still uses its previously saved, immutable blocks.
    """
    try:
        source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:
        raise PlanValidationError("RENDER_CONTRACT_UNAVAILABLE") from exc
    return digest({"renderer_source_sha256": source_hash, "metrics": METRICS,
                   "disclosures": DISCLOSURES, "template_version": TEMPLATE_VERSION})


def _fail(code):
    raise PlanValidationError(code)


def heading_for(claim, facts):
    if claim["type"] in {"LIMITATION", "UNAVAILABLE"}:
        return "EVIDENCE_GAPS"
    if claim["type"] == "NEXT_ACTION":
        return "NEXT_STEPS"
    if not claim["fact_refs"]:
        _fail("CLAIM_WITHOUT_FACT")
    return METRICS[facts[claim["fact_refs"][0]]["metric_id"]][3]


def validate_catalog(report):
    from engine.claim_builder import catalog_digest
    if report.get("template_version") != TEMPLATE_VERSION or report.get("render_contract_hash") != current_render_contract_hash():
        _fail("RENDER_CONTRACT_INCOMPATIBLE")
    if report.get("catalog_hash") != catalog_digest(report):
        _fail("CATALOG_HASH_MISMATCH")
    facts = {f["fact_id"]: f for f in report["facts"]}
    claims = {c["claim_id"]: c for c in report["claims"]}
    assessments = {a["assessment_id"]: a for a in report["assessments"]}
    evidence = {e["evidence_id"]: e for e in report["evidence"]}
    if len(facts) != len(report["facts"]) or len(claims) != len(report["claims"]):
        _fail("DUPLICATE_CATALOG_ID")
    for fact in facts.values():
        original = {k: v for k, v in fact.items() if k != "fact_id"}
        if stable_id("f", original) != fact["fact_id"] or fact["report_id"] != report["report_id"] or fact["manifest_hash"] != report["manifest_hash"]:
            _fail("FACT_OWNERSHIP_OR_HASH")
        if fact["metric_id"] not in METRICS or fact["unit"] != METRICS[fact["metric_id"]][1] or not set(fact["evidence_ids"]) <= set(evidence):
            _fail("FACT_METRIC_OR_EVIDENCE")
        record = report["filter_registry"].get(fact["selection"]["filter_spec_id"])
        if not record or digest(record["spec"]) != fact["selection"]["filter_digest"]:
            _fail("FILTER_DIGEST_MISMATCH")
        if fact["data_kind"] not in {"OBSERVED", "DERIVED", "USER_PLAN"}:
            _fail("UNAPPROVED_DATA_KIND")
    for claim in claims.values():
        if claim["report_id"] != report["report_id"] or stable_id("cl", {k: v for k, v in claim.items() if k != "claim_id"}) != claim["claim_id"]:
            _fail("CLAIM_OWNERSHIP_OR_HASH")
        if not set(claim["fact_refs"]) <= set(facts) or not set(claim["assessment_refs"]) <= set(assessments):
            _fail("UNKNOWN_CLAIM_DEPENDENCY")
        if set(claim["evidence_refs"]) != {e for fid in claim["fact_refs"] for e in facts[fid]["evidence_ids"]}:
            _fail("CITATION_BINDING_MISMATCH")
        if not set(claim["required_disclosures"]) <= set(DISCLOSURES):
            _fail("UNKNOWN_DISCLOSURE")
        if claim["type"] in {"OBSERVATION", "USER_PLAN"} and any(facts[fid]["value"]["kind"] == "UNKNOWN" for fid in claim["fact_refs"]):
            _fail("UNKNOWN_VALUE_NOT_OBSERVATION")
        if claim["type"] in {"COMPARISON", "DIFFERENCE", "PERIOD_CHANGE"}:
            if not claim["assessment_refs"] or len(claim["fact_refs"]) != 2:
                _fail("MISSING_OPERATION_ASSESSMENT")
            for aid in claim["assessment_refs"]:
                assessment = assessments[aid]
                if assessment["report_id"] != report["report_id"] or assessment["qualification"] != "QUALIFIED" or not set(claim["fact_refs"]) <= set(assessment["fact_refs"]):
                    _fail("ASSESSMENT_INELIGIBLE")
            if claim["type"] in {"COMPARISON", "DIFFERENCE"}:
                operands = claim.get("operands") or {}
                if set(operands) != {"left_fact_id", "right_fact_id"} or set(operands.values()) != set(claim["fact_refs"]):
                    _fail("INVALID_OPERAND_ROLES")
                left, right = facts[operands["left_fact_id"]], facts[operands["right_fact_id"]]
                city_difference = (claim["type"] == "DIFFERENCE" and left["metric_id"] == right["metric_id"] == "gcis.city_new_companies"
                                   and left["subject"] == right["subject"] and left["selection"] == right["selection"]
                                   and left["period"]["start"] > right["period"]["end"])
                if not comparable(left, right) and not city_difference:
                    _fail("NOT_COMPARABLE")
                purpose = "WITHIN_SERIES_CHANGE" if city_difference else "CROSS_REGION_COMPARISON"
                if any(assessments[aid]["purpose"] != purpose for aid in claim["assessment_refs"]):
                    _fail("ASSESSMENT_PURPOSE_MISMATCH")
            else:
                operands = claim.get("operands") or {}
                if set(operands) != {"current_fact_id", "baseline_fact_id"} or set(operands.values()) != set(claim["fact_refs"]):
                    _fail("INVALID_PERIOD_OPERANDS")
                current, baseline = (facts[operands[k]] for k in ("current_fact_id", "baseline_fact_id"))
                if current["metric_id"] != "gcis.city_new_companies" or current["metric_id"] != baseline["metric_id"] or current["selection"] != baseline["selection"] or current["subject"] != baseline["subject"] or Decimal(baseline["value"]["amount"]) <= 0:
                    _fail("INVALID_PERIOD_CHANGE")
                if any(assessments[aid]["purpose"] != "WITHIN_SERIES_CHANGE" for aid in claim["assessment_refs"]):
                    _fail("ASSESSMENT_PURPOSE_MISMATCH")
        elif claim.get("operands") is not None:
            _fail("UNEXPECTED_OPERANDS")
        heading_for(claim, facts)
    return facts, claims


def validate_answer_plan(report, plan):
    facts, claims = validate_catalog(report)
    if not isinstance(plan, dict) or set(plan) != {"report_id", "catalog_hash", "sections"}:
        _fail("PLAN_FIELDS")
    if plan["report_id"] != report["report_id"] or plan["catalog_hash"] != report["catalog_hash"]:
        _fail("PLAN_VERSION_OR_OWNER")
    sections = plan["sections"]
    if not isinstance(sections, list) or not 1 <= len(sections) <= 6:
        _fail("PLAN_SECTION_COUNT")
    headings, used = set(), set()
    for section in sections:
        if not isinstance(section, dict) or set(section) != {"heading_id", "claim_ids"}:
            _fail("SECTION_FIELDS")
        heading = section["heading_id"]
        if heading not in HEADINGS or heading in headings:
            _fail("SECTION_HEADING")
        headings.add(heading)
        ids = section["claim_ids"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= 12 or any(not isinstance(cid, str) for cid in ids):
            _fail("PLAN_CLAIM_COUNT")
        for cid in ids:
            if cid not in claims or cid in used:
                _fail("UNKNOWN_OR_DUPLICATE_CLAIM")
            if heading_for(claims[cid], facts) != heading:
                _fail("CLAIM_HEADING_MISMATCH")
            used.add(cid)
    return plan


def default_answer_plan(report, *, question=""):
    facts = {f["fact_id"]: f for f in report["facts"]}
    grouped = {h: [] for h in HEADINGS}
    def pair_key(claim):
        operands = claim.get("operands") or {}
        if claim["type"] in {"COMPARISON", "DIFFERENCE"} and set(operands) == {"left_fact_id", "right_fact_id"}:
            return tuple(sorted(operands.values()))
        return None
    # Both registered operations currently render the same comparison sentence.
    # Prefer the explicit difference, irrespective of Catalog insertion order.
    differences = {pair_key(c) for c in report["claims"] if c["type"] == "DIFFERENCE"}
    seen_pairs = set()
    for claim in report["claims"]:
        if claim["type"] == "LIMITATION":
            continue  # The renderer includes every report-wide limitation below.
        pair = pair_key(claim)
        if pair is not None:
            if (claim["type"] == "COMPARISON" and pair in differences) or pair in seen_pairs:
                continue
            seen_pairs.add(pair)
        grouped[heading_for(claim, facts)].append(claim)
    # This is controlled selection, not new reasoning or generated prose. All
    # necessary report-wide disclosures remain mandatory in the renderer.
    if question:
        gaps = [c for c in grouped["EVIDENCE_GAPS"] if c["type"] == "UNAVAILABLE"][:2]
        if any(w in question for w in ("排名", "限制", "不能", "缺口", "資料不足")):
            grouped = {"EVIDENCE_GAPS": gaps, "NEXT_STEPS": grouped["NEXT_STEPS"][:2]}
        elif any(w in question for w in ("計畫", "每月目標", "月目標", "規劃")):
            grouped = {"HIRING_PLAN": grouped["HIRING_PLAN"]}
        elif any(w in question.casefold() for w in ("gcis", "公司", "同業")):
            grouped = {"GCIS_CONTEXT": grouped["GCIS_CONTEXT"], "EVIDENCE_GAPS": gaps}
        elif any(w in question for w in ("比較", "多", "差", "少", "最多")):
            comparisons = [c for c in grouped["PUBLIC_JOB_OBSERVATIONS"] if c["type"] in {"COMPARISON", "DIFFERENCE"}]
            grouped = {"PUBLIC_JOB_OBSERVATIONS": comparisons} if comparisons else {"EVIDENCE_GAPS": gaps, "NEXT_STEPS": grouped["NEXT_STEPS"][:2]}
    sections = [{"heading_id": h, "claim_ids": [c["claim_id"] for c in rows[:12]]} for h, rows in grouped.items() if rows]
    if not sections:
        limitations = [c["claim_id"] for c in report["claims"] if c["type"] == "LIMITATION"]
        sections = [{"heading_id": "EVIDENCE_GAPS", "claim_ids": limitations[:12]}]
    return {"report_id": report["report_id"], "catalog_hash": report["catalog_hash"], "sections": sections}


def _display(value):
    d = Decimal(value)
    return f"{int(d):,}" if d == d.to_integral_value() else format(d, ",f").rstrip("0").rstrip(".")


def _period(fact):
    p = fact["period"]
    return p["start"] if p["start"] == p["end"] else f"{p['start']}～{p['end']}"


def _observation(fact):
    district = fact["subject"]["district"] or "臺中市全市"
    metric = fact["metric_id"]
    label, unit, _, _ = METRICS[metric]
    units = {"person": "人", "posting": "筆", "company_name": "個不同名稱", "company": "家", "TWD": "元", "factory": "家"}
    n = _display(fact["value"]["amount"])
    qualifier = "至少" if fact["quality"]["value_status"] == "LOWER_BOUND" else ""
    if fact["data_kind"] == "USER_PLAN":
        return f"{_period(fact)}，你的淨到職目標為 {n} 人；這是規劃，不是可招到人數預測。"
    if metric.startswith("jobs."):
        keyword = fact["selection"]["occupation_keyword"] or "全部職類"
        quoted_keyword = json.dumps(keyword, ensure_ascii=False)
        return f"{_period(fact)}，{district}符合職務文字條件 {quoted_keyword} 的{label}為{qualifier} {n} {units[unit]}。"
    if metric.startswith("gcis.local") and fact["quality"]["value_status"] == "SAMPLE_MATCH_ZERO":
        return f"{_period(fact)}，{district}中類 {fact['selection']['manufacturing_division']} 的已分類樣本未觀察到{label.replace('已分類樣本', '')}；不能解讀為該區沒有同業活動。"
    industry = f"中類 {fact['selection']['manufacturing_division']} " if metric.startswith("gcis.local") else ""
    if fact["subject"]["district"] is None and label.startswith("全市"):
        return f"{_period(fact)}，臺中市{label}為 {n} {units[unit]}。"
    return f"{_period(fact)}，{district}{industry}的{label}為 {n} {units[unit]}。"


def render_answer_plan(report, plan):
    validate_answer_plan(report, plan)
    facts = {f["fact_id"]: f for f in report["facts"]}
    claims = {c["claim_id"]: c for c in report["claims"]}
    blocks, selected_ids = [], []
    # Global evidence gaps are mandatory even when a model chooses only good news.
    required = {d["code"] for d in report.get("disclosures", [])}
    from engine.claim_builder import ACTION_TEMPLATES
    for section in plan["sections"]:
        for cid in section["claim_ids"]:
            c = claims[cid]
            selected_ids.append(cid)
            required.update(c["required_disclosures"])
            kind = c["type"]
            if kind == "LIMITATION":
                continue
            if kind in {"OBSERVATION", "USER_PLAN"}:
                text = _observation(facts[c["fact_refs"][0]])
            elif kind == "UNAVAILABLE":
                if c["template_id"] != "unknown_local_metric" or len(c["fact_refs"]) != 1:
                    _fail("UNKNOWN_UNAVAILABLE_TEMPLATE")
                fact = facts[c["fact_refs"][0]]
                if fact["value"]["kind"] != "UNKNOWN":
                    _fail("UNAVAILABLE_TEMPLATE_REQUIRES_UNKNOWN")
                label = METRICS[fact["metric_id"]][0]
                text = f"{_period(fact)}，{fact['subject']['district']}中類 {fact['selection']['manufacturing_division']} 的{label}目前未知；來源、分類或前後狀態證據不足，不能以0解讀。"
            elif kind in {"COMPARISON", "DIFFERENCE"}:
                left, right = (facts[c["operands"][k]] for k in ("left_fact_id", "right_fact_id"))
                lv, rv = Decimal(left["value"]["amount"]), Decimal(right["value"]["amount"])
                a, b = left["subject"]["district"], right["subject"]["district"]
                label, unit = METRICS[left["metric_id"]][:2]
                u = {"posting": "筆", "person": "人", "company_name": "個不同名稱", "company": "家"}[unit]
                if left["metric_id"] == "gcis.city_new_companies":
                    text = f"臺中市全市製造業新設公司，{_period(left)}為 {_display(str(lv))} 家，{_period(right)}為 {_display(str(rv))} 家；絕對差額 {_display(str(lv-rv))} 家。基期為零不計算百分比。"
                elif lv == rv:
                    text = f"同一快照與篩選下，{a}與{b}的可觀測{label}相同（各 {_display(str(lv))} {u}）。"
                else:
                    high, low = (a, b) if lv > rv else (b, a)
                    text = f"同一快照與篩選下，{high}的可觀測{label}比{low}多 {_display(str(abs(lv-rv)))} {u}；這是公開樣本差異。"
            elif kind == "PERIOD_CHANGE":
                current, baseline = (facts[c["operands"][k]] for k in ("current_fact_id", "baseline_fact_id"))
                delta = (Decimal(current["value"]["amount"]) / Decimal(baseline["value"]["amount"]) - 1) * 100
                percent = delta.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                direction = "增加" if delta > 0 else "減少" if delta < 0 else "不變"
                text = f"臺中市全市製造業新設公司，{_period(current)}相對{_period(baseline)}{direction} {_display(str(abs(percent)))}%；不是行政區招聘需求或企業存量淨增。"
            elif kind == "NEXT_ACTION":
                action = c["template_id"].removeprefix("action:")
                if action not in ACTION_TEMPLATES:
                    _fail("UNKNOWN_ACTION_TEMPLATE")
                label, reason = ACTION_TEMPLATES[action]
                district = facts[c["fact_refs"][0]]["subject"]["district"] if c["fact_refs"] else None
                text = f"{district + '：' if district else ''}{label}：{reason}"
            else:
                _fail("UNSUPPORTED_CLAIM_TEMPLATE")
            first = facts[c["fact_refs"][0]] if c["fact_refs"] else None
            blocks.append({"type": "claim", "heading_id": section["heading_id"], "heading": HEADINGS[section["heading_id"]],
                           "claim_id": cid, "text": text, "fact_ids": c["fact_refs"], "evidence_ids": c["evidence_refs"],
                           "rule_id": c["rule_id"], "metric_id": first["metric_id"] if first else None,
                           "district": first["subject"]["district"] if first else None})
    for code in sorted(required):
        if code not in DISCLOSURES:
            _fail("UNKNOWN_MANDATORY_DISCLOSURE")
        blocks.append({"type": "disclosure", "heading_id": "EVIDENCE_GAPS", "heading": HEADINGS["EVIDENCE_GAPS"],
                       "claim_id": None, "code": code, "text": DISCLOSURES[code], "fact_ids": [], "evidence_ids": [], "rule_id": "DISCLOSURE_V1"})
    return {"blocks": blocks, "claim_ids": selected_ids, "render_digest": digest({"blocks": blocks, "manifest_hash": report["manifest_hash"],
                                                                                 "template_version": TEMPLATE_VERSION,
                                                                                 "render_contract_hash": report["render_contract_hash"]}),
            "template_version": TEMPLATE_VERSION, "render_contract_hash": report["render_contract_hash"],
            "consistency_status": "CONSISTENT_WITH_APPROVED_SNAPSHOT"}
