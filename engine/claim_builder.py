"""Build a server-owned catalog. Model output never creates quantities or claims."""
from __future__ import annotations

import itertools
from decimal import Decimal

from engine.fact_ledger import (DISCLOSURES, METRICS, FactLedger, amount, comparable,
                                digest, normal_keyword, quality, stable_id, valid_period)

RULES_VERSION = "report-claims-v1"
JOB_FIELDS = {"jobs.vacancy_postings": "vacancy_postings", "jobs.requested_workers": "requested_workers",
              "jobs.distinct_company_names": "distinct_companies"}
ACTION_TEMPLATES = {
    "CHECK_RELATED_JOB_CHANNELS": ("查證相關職類的徵才動向", "已觀察到公司活動；請另外核對同職類公開刊登與實際招募渠道。"),
    "COMPLETE_GCIS_EVIDENCE": ("補齊同業公司事件證據", "來源或分類不足，先補齊清冊與可用性紀錄。"),
    "CONFIRM_HIRING_CONDITIONS": ("確認職務、薪資、班別與招募時程", "公開樣本無法判定單一企業招聘成敗，請補企業自己的條件。"),
}


def catalog_digest(content: dict) -> str:
    core = {key: content.get(key, [] if key != "filter_registry" else {}) for key in
            ("facts", "claims", "assessments", "evidence", "filter_registry")}
    core.update(template_version=content.get("template_version"), render_contract_hash=content.get("render_contract_hash"))
    return digest(core)


def _months(start: str, end: str) -> list[str]:
    if not valid_period(start) or not valid_period(end) or len(start) != 7 or len(end) != 7 or end < start:
        raise ValueError("INVALID_MONTH_WINDOW")
    y, m = map(int, start.split("-"))
    out = []
    while f"{y:04}-{m:02}" <= end:
        out.append(f"{y:04}-{m:02}")
        if len(out) > 240:
            raise ValueError("MONTH_WINDOW_TOO_LONG")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def build_report_content(report_id, scenario, manifest, jobs, gcis, planning, background=None) -> dict:
    """Consume only approved server-side tool results; never client/model facts.

    Missing data creates explicit limitations. All source periods and proxy
    classifications remain attached to their own facts.
    """
    ledger = FactLedger(report_id, manifest)
    claims, assessments, metric_groups, next_actions = [], [], [], []
    disclosures = {"CONSISTENCY_SCOPE", "PUBLIC_SNAPSHOT_NOT_SHORTAGE", "OCCUPATION_PROXY", "COMPANY_NAMES_NOT_ENTITIES",
                   "USER_PLAN_NOT_FORECAST", "CAUSE_UNKNOWN", "NET_CHANGE_BLOCKED"}
    districts = list(scenario["districts"])
    keyword = scenario["occupation"]["keyword"]
    profile = scenario["occupation"]["retrieval_profile_version"]
    division = scenario["manufacturing"]["division_code"]
    classification = scenario["manufacturing"]["classification_version"]

    def selection(basis, *, industry=None, occupation=None, version=classification, expression=None):
        return {"manufacturing_division": industry, "occupation_keyword": occupation,
                "classification_basis": basis, "classification_version": version,
                **ledger.filter({"version": version, "expression": expression or {"op": "ALL"}})}

    def assess(facts, purpose, qualified, population, reasons=(), source="retained-report-input"):
        item = {"report_id": report_id, "purpose": purpose, "population_scope": population,
                "fact_refs": [f["fact_id"] for f in facts],
                "scope_digest": digest([{"subject": f["subject"], "selection": f["selection"]} for f in facts]),
                "period_digest": digest([f["period"] for f in facts]), "source_release": source,
                "classification_version": classification,
                "qualification": "QUALIFIED" if qualified else "UNAVAILABLE",
                "comparison_status": "COMPARABLE_SAMPLE" if qualified else "NOT_COMPARABLE", "reason_codes": list(reasons)}
        item["assessment_id"] = stable_id("as", item)
        assessments.append(item)
        return item

    def claim(kind, facts=(), *, rule="OBSERVED_VALUE_V1", template="observation", required=(), assessment=(), operands=None):
        operation = {"OBSERVATION": "IDENTITY", "COMPARISON": "COMPARE", "DIFFERENCE": "ABSOLUTE_DIFFERENCE",
                     "PERIOD_CHANGE": "RELATIVE_CHANGE", "USER_PLAN": "PLAN_SPLIT"}.get(kind, "RULE_TEMPLATE")
        item = {"report_id": report_id, "type": kind, "fact_refs": [f["fact_id"] for f in facts],
                "operands": operands, "assessment_refs": [a["assessment_id"] for a in assessment],
                "rule_id": rule, "operation": operation, "template_id": template,
                "required_disclosures": sorted(set(required)),
                "evidence_refs": sorted({e for f in facts for e in f["evidence_ids"]}), "rules_version": RULES_VERSION}
        item["claim_id"] = stable_id("cl", item)
        if item["claim_id"] not in {c["claim_id"] for c in claims}:
            claims.append(item)
        disclosures.update(required)
        return item

    job_selection = selection("OCCUPATION_TEXT_PROXY", occupation=keyword, version=profile,
                              expression={"op": "AND", "args": [{"op": "PROFILE", "id": "IND_MFG", "version": profile},
                                                                   {"op": "CONTAINS_ANY_OCCUPATION_FIELD", "term": normal_keyword(keyword)}]})
    snapshot = jobs.get("snapshot_date") if isinstance(jobs, dict) else None
    rows = jobs.get("comparisons", []) if isinstance(jobs, dict) else []
    jobs_valid = bool(jobs.get("available") and valid_period(snapshot) and len(snapshot) == 10
                      and len(rows) == len(districts) and {r.get("district") for r in rows} == set(districts)
                      and normal_keyword(jobs.get("occupation_keyword") or "") == normal_keyword(keyword)
                      and jobs.get("industry_id") == "IND_MFG")
    pinned_jobs = manifest.get("resolved_periods", {}).get("jobs")
    if isinstance(pinned_jobs, dict):
        pinned_jobs = pinned_jobs.get("snapshot_date") or pinned_jobs.get("date")
    if isinstance(pinned_jobs, str) and snapshot != pinned_jobs:
        jobs_valid = False
    jobs_by_metric = {metric: [] for metric in JOB_FIELDS}
    all_capped = any(r.get("coverage_status") == "QUERY_LIMIT_REACHED" or r.get("limit_reached_districts") for r in rows)
    if all_capped:
        disclosures.add("QUERY_LIMIT_REACHED")
    for metric, field in JOB_FIELDS.items():
        group = {"metric_id": metric, "label": METRICS[metric][0], "unit": METRICS[metric][1],
                 "comparison_status": "NOT_COMPARABLE", "rows": []}
        for district in districts:
            row = next((r for r in rows if r.get("district") == district), {})
            raw = row.get(field)
            okay = jobs_valid and row.get("coverage_status") in {"QUERY_LIMIT_REACHED", "OBSERVED_SNAPSHOT_COMPLETE_WITHIN_QUERY_LIMIT"}
            try:
                if okay:
                    amount(raw, count=True)
                    ev = row.get("evidence") or jobs.get("evidence") or {}
                    if ev.get("data_period") and ev["data_period"] != snapshot:
                        raise ValueError("SNAPSHOT_SCOPE_MISMATCH")
                    geography = str(ev.get("geography") or "")
                    if geography and district not in geography:
                        raise ValueError("GEOGRAPHIC_SCOPE_MISMATCH")
                    eid = ledger.evidence_for("jobs", {"snapshot_date": snapshot, "district": district, field: raw}, ev)
                    capped = bool(row.get("coverage_status") == "QUERY_LIMIT_REACHED" or row.get("limit_reached_districts"))
                    q = quality("PUBLISHED_VACANCIES", capped=capped)
                    if all_capped:
                        q["comparison_status"] = "DESCRIPTIVE_ONLY"
                    fact = ledger.add(metric, raw, district=district, start=snapshot, selection=job_selection,
                                      evidence_ids=[eid], point_quality=q)
                    jobs_by_metric[metric].append(fact)
                    claim("OBSERVATION", [fact], required=["PUBLIC_SNAPSHOT_NOT_SHORTAGE", "OCCUPATION_PROXY"] + (["QUERY_LIMIT_REACHED"] if capped else []))
                    group["rows"].append({"district": district, "fact_id": fact["fact_id"], "value": fact["value"]["amount"],
                                          "value_status": q["value_status"], "qualification": q["qualification"]})
                    continue
            except (ValueError, TypeError):
                pass
            disclosures.add("JOBS_UNAVAILABLE")
            group["rows"].append({"district": district, "fact_id": None, "value": None,
                                  "value_status": "UNKNOWN", "qualification": "UNAVAILABLE"})
        facts = jobs_by_metric[metric]
        can_compare = len(facts) == len(districts) and not all_capped and all(comparable(a, b) for a, b in itertools.combinations(facts, 2))
        if facts:
            assessment = assess(facts, "CROSS_REGION_COMPARISON", can_compare, "PUBLISHED_VACANCIES",
                                [] if can_compare else ["JOBS_COMPARISON_INELIGIBLE"], source=snapshot or "unknown")
            if can_compare:
                group["comparison_status"] = "COMPARABLE_SAMPLE"
                for left, right in itertools.combinations(facts, 2):
                    operands = {"left_fact_id": left["fact_id"], "right_fact_id": right["fact_id"]}
                    for kind in ("COMPARISON", "DIFFERENCE"):
                        claim(kind, [left, right], operands=operands, assessment=[assessment], required=["PUBLIC_SNAPSHOT_NOT_SHORTAGE", "OCCUPATION_PROXY"])
        metric_groups.append(group)

    # Current GCIS context and local classified samples are separate populations.
    gcis = gcis or {}
    city = gcis.get("city") or {}
    city_facts = []
    city_selection = selection("CITY_OFFICIAL_CLASSIFICATION", expression={"op": "OFFICIAL_INDUSTRY", "code": "C", "level": "major"})
    if city.get("available"):
        try:
            eid = ledger.evidence_for("gcis", city, city.get("evidence"))
            for prefix, field in (("", "current_sum"), ("baseline_", "baseline_sum")):
                start = city.get(prefix + "start") if prefix else city.get("start")
                end = city.get(prefix + "end") if prefix else city.get("end")
                if start and end and city.get(field) is not None:
                    fact = ledger.add("gcis.city_new_companies", city[field], district=None, start=start, end=end,
                                      period_kind="MONTH_WINDOW", role="CITY_AGGREGATE", selection=city_selection,
                                      population="OFFICIAL_CITY_AGGREGATE", evidence_ids=[eid])
                    city_facts.append(fact)
                    claim("OBSERVATION", [fact], required=["CITY_NOT_DISTRICT"])
            if len(city_facts) == 2:
                current, baseline = city_facts
                expected = _months(baseline["period"]["start"], current["period"]["end"])
                history = city.get("monthly_rows") or []
                observed = {}
                for row in history:
                    month = row.get("year_month") or row.get("period")
                    val = row.get("new_company_count", row.get("new_companies", row.get("companies")))
                    if month in observed:
                        raise ValueError("DUPLICATE_CITY_MONTH")
                    observed[month] = Decimal(amount(val, count=True))
                current_months = _months(current["period"]["start"], current["period"]["end"])
                baseline_months = _months(baseline["period"]["start"], baseline["period"]["end"])
                complete = len(current_months) == len(baseline_months) == 12 and baseline_months + current_months == expected and set(expected) <= set(observed)
                if complete:
                    complete = all(sum(observed[m] for m in _months(f["period"]["start"], f["period"]["end"])) == Decimal(f["value"]["amount"]) for f in city_facts)
                a = assess(city_facts, "WITHIN_SERIES_CHANGE", complete, "OFFICIAL_CITY_AGGREGATE",
                           [] if complete else ["INCOMPLETE_CITY_WINDOW"])
                if complete:
                    up = Decimal(current["value"]["amount"]) > Decimal(baseline["value"]["amount"])
                    down = Decimal(current["value"]["amount"]) < Decimal(baseline["value"]["amount"])
                    rule = "GS01_CITY_NEW_UP" if up else "GS02_CITY_NEW_DOWN" if down else "CITY_UNCHANGED"
                    if Decimal(baseline["value"]["amount"]) > 0:
                        claim("PERIOD_CHANGE", city_facts, rule=rule, operands={"current_fact_id": current["fact_id"], "baseline_fact_id": baseline["fact_id"]},
                              assessment=[a], required=["CITY_NOT_DISTRICT", "NET_CHANGE_BLOCKED"])
                    else:
                        claim("DIFFERENCE", city_facts, rule=rule, operands={"left_fact_id": current["fact_id"], "right_fact_id": baseline["fact_id"]},
                              assessment=[a], required=["CITY_NOT_DISTRICT", "NET_CHANGE_BLOCKED"])
        except (ValueError, TypeError, KeyError):
            disclosures.add("GCIS_PARTIAL")
    else:
        disclosures.add("GCIS_UNAVAILABLE")

    local_rows = gcis.get("local") or []
    local_trace = {}
    local_metrics = (("gcis.local_new_companies", "new_company_count"),
                     ("gcis.local_capital_increase_companies", "capital_increase_company_count"),
                     ("gcis.local_dissolved_companies", "dissolved_company_count"))
    for row in local_rows:
        district = row.get("district")
        if district not in districts or str(row.get("industry_code")) != str(division):
            continue
        local_selection = selection("TAX_PRIMARY_INDUSTRY", industry=division,
                                    expression={"op": "REGISTERED_EVENT_CLASSIFICATION", "division": division, "version": classification})
        # Missing data is itself traceable. Preserve the approved adapter's
        # classification/availability evidence before considering any quantity.
        eid = ledger.evidence_for("gcis", row, row.get("evidence"))
        local_trace[district] = {"evidence_ids": [eid], "reason_codes": list(row.get("reason_codes") or ["GQ_LOCAL_VALUE_UNAVAILABLE"])}

        def add_unknown(metric, reasons):
            try:
                q = quality("CLASSIFIED_EVENT_SAMPLE", available=False, reasons=reasons)
                fact = ledger.add(metric, None, district=district, start=row["start"], end=row["end"],
                                  period_kind="MONTH_WINDOW", role="REGISTERED_ADDRESS", selection=local_selection,
                                  population="CLASSIFIED_EVENT_SAMPLE", evidence_ids=[eid], point_quality=q)
                claim("UNAVAILABLE", [fact], rule="GS07_SOURCE_UNAVAILABLE", template="unknown_local_metric",
                      required=["GCIS_UNAVAILABLE", "GCIS_LOCAL_SAMPLE"])
            except (ValueError, KeyError, TypeError):
                # Invalid/missing period cannot be disguised as a dated fact;
                # its evidence still remains linked directly from the row.
                local_trace[district]["reason_codes"] = sorted(set(local_trace[district]["reason_codes"] + ["GQ_LOCAL_PERIOD_UNAVAILABLE"]))

        if not row.get("available"):
            disclosures.add("GCIS_UNAVAILABLE")
            for metric, _ in local_metrics:
                add_unknown(metric, local_trace[district]["reason_codes"])
            continue
        partial = row.get("qualification") != "QUALIFIED" or bool(row.get("reason_codes"))
        if partial:
            disclosures.add("GCIS_PARTIAL")
        for metric, field in local_metrics:
            if row.get(field) is None:
                disclosures.add("GCIS_PARTIAL")
                add_unknown(metric, sorted(set(local_trace[district]["reason_codes"] + ["GQ_LOCAL_VALUE_UNAVAILABLE"])))
                continue
            try:
                numeric = amount(row[field], count=True)
                event_kind = {"new_company_count": "setup", "capital_increase_company_count": "change", "dissolved_company_count": "dissolved"}[field]
                evidence = row.get("evidence") or {}
                event_status = evidence.get("per_event_status", {}).get(event_kind, {})
                if event_status and not event_status.get("available"):
                    disclosures.add("GCIS_PARTIAL")
                    add_unknown(metric, sorted(set(local_trace[district]["reason_codes"] + ["GQ_EVENT_KIND_UNAVAILABLE"])))
                    continue
                if numeric == "0" and partial and not event_status.get("available"):
                    disclosures.add("GCIS_PARTIAL")
                    add_unknown(metric, sorted(set(local_trace[district]["reason_codes"] + ["GQ_SAMPLE_NOT_DEFINED"])))
                    continue  # Partial source with no defined sample is not zero.
                q = quality("CLASSIFIED_EVENT_SAMPLE", partial=partial, zero_sample=numeric == "0", reasons=row.get("reason_codes") or [])
                coverage = evidence.get("coverage", {}).get(event_kind, {})
                q["classification_denominator_scope"] = coverage.get("denominator_scope")
                q["classification_ratio"] = coverage.get("classification_ratio")
                fact = ledger.add(metric, row[field], district=district, start=row["start"], end=row["end"],
                                  period_kind="MONTH_WINDOW", role="REGISTERED_ADDRESS", selection=local_selection,
                                  population="CLASSIFIED_EVENT_SAMPLE", evidence_ids=[eid], point_quality=q)
                rule = "GS05_SAMPLE_ZERO" if numeric == "0" else "GS03_LOCAL_ACTIVITY"
                claim("OBSERVATION", [fact], rule=rule, required=["GCIS_LOCAL_SAMPLE"] + (["GCIS_PARTIAL"] if partial else []))
                if int(numeric) > 0:
                    add = {"action_id": "CHECK_RELATED_JOB_CHANNELS", "rule_id": rule, "district": district}
                    if add not in next_actions:
                        next_actions.append(add)
            except (ValueError, KeyError, TypeError):
                disclosures.add("GCIS_PARTIAL")
                add_unknown(metric, sorted(set(local_trace[district]["reason_codes"] + ["GQ_LOCAL_VALUE_INVALID"])))
    if not city_facts and not any(f["metric_id"].startswith("gcis.local") and f["value"]["amount"] is not None for f in ledger.facts):
        disclosures.add("GCIS_UNAVAILABLE")
    if "GCIS_UNAVAILABLE" in disclosures or "GCIS_PARTIAL" in disclosures:
        next_actions.insert(0, {"action_id": "COMPLETE_GCIS_EVIDENCE", "rule_id": "GS07_SOURCE_UNAVAILABLE", "district": None})
    if any(c["rule_id"] in {"GS01_CITY_NEW_UP", "GS02_CITY_NEW_DOWN"} for c in claims):
        next_actions.append({"action_id": "CHECK_RELATED_JOB_CHANNELS", "rule_id": "GS01_CITY_NEW_UP" if any(c["rule_id"] == "GS01_CITY_NEW_UP" for c in claims) else "GS02_CITY_NEW_DOWN", "district": None})

    # Recompute the confirmed plan; never trust a supplied distribution as facts.
    plan = scenario["hiring_plan"]
    months = _months(plan["start_month"], plan["end_month"])
    hires = plan["net_hires"]
    if isinstance(hires, bool) or not isinstance(hires, int) or not 1 <= hires <= 100000 or not 1 <= len(months) <= 12:
        raise ValueError("INVALID_HIRING_PLAN")
    expected_targets = [{"month": month, "people": hires // len(months) + (i < hires % len(months))} for i, month in enumerate(months)]
    if isinstance(planning, dict) and planning.get("monthly_targets") is not None and planning["monthly_targets"] != expected_targets:
        raise ValueError("PLANNING_DISTRIBUTION_MISMATCH")
    plan_eid = ledger.evidence_for("plan", plan)
    plan_selection = selection("USER_PLAN", expression={"op": "CONFIRMED_SCENARIO", "formula": "quotient-remainder-first-months-v1"})
    for target in expected_targets:
        fact = ledger.add("plan.monthly_net_hires", target["people"], district=None, start=target["month"],
                          period_kind="PLAN_MONTH", role="USER_SELECTION", selection=plan_selection,
                          population="USER_PLAN", data_kind="USER_PLAN", evidence_ids=[plan_eid])
        claim("USER_PLAN", [fact], rule="PLAN_SPLIT_V1", required=["USER_PLAN_NOT_FORECAST"])

    background = background or {}
    wage = background.get("wage") or background.get("wage_baseline") or {}
    if wage.get("available") and wage.get("average_insured_salary") is not None:
        period = wage.get("data_period", "")
        if isinstance(period, str) and len(period) == 5 and period.isdigit():
            period = f"{int(period[:3]) + 1911}-{period[3:]}"
        try:
            eid = ledger.evidence_for("wage", wage, wage.get("evidence"))
            fact = ledger.add("wage.average_insured_salary", wage["average_insured_salary"], district=None, start=period,
                              role="CITY_AGGREGATE", selection=selection("CITY_OFFICIAL_CLASSIFICATION", expression={"op": "AND", "args": [
                                  {"op": "EQUALS", "field": "region_code", "value": "66"},
                                  {"op": "EQUALS", "field": "industry_code", "value": "C"},
                                  {"op": "EQUALS", "field": "unit_type_code", "value": "1"},
                                  {"op": "EQUALS", "field": "employment_insurance_code", "value": "1"}]}),
                              population="OFFICIAL_CITY_AGGREGATE", evidence_ids=[eid])
            claim("OBSERVATION", [fact], required=["INSURED_NOT_TAKE_HOME", "CITY_NOT_DISTRICT"])
        except (ValueError, TypeError):
            pass

    for factory in background.get("factories", []):
        if not factory.get("available") or factory.get("district") not in districts:
            continue
        try:
            if factory.get("industry_code") is not None and str(factory["industry_code"]) != str(division):
                continue
            eid = ledger.evidence_for("factory", factory, factory.get("evidence"))
            fact = ledger.add("factory.registered_factories", factory["factory_count"], district=factory["district"], start=factory["period"],
                              role="FACTORY_LOCATION", selection=selection("REVIEWED_FACTORY_MAPPING", industry=division,
                              expression={"op": "REVIEWED_FACTORY_DIVISION", "division": division, "version": classification}),
                              population="FACTORY_REGISTER", evidence_ids=[eid],
                              point_quality=quality("FACTORY_REGISTER", partial=True))
            claim("OBSERVATION", [fact], required=["FACTORY_NOT_HIRING"])
        except (ValueError, TypeError, KeyError):
            pass

    # Descriptive local metrics remain present for every chosen district, with
    # nulls instead of fabricated zeros when source/classification is unavailable.
    for metric in ("gcis.local_new_companies", "gcis.local_capital_increase_companies", "gcis.local_dissolved_companies", "factory.registered_factories"):
        relevant = {f["subject"]["district"]: f for f in ledger.facts if f["metric_id"] == metric}
        metric_groups.append({"metric_id": metric, "label": METRICS[metric][0], "unit": METRICS[metric][1],
                              "comparison_status": "DESCRIPTIVE_ONLY", "rows": [
                                  {"district": district, "fact_id": relevant[district]["fact_id"] if district in relevant else None,
                                   "value": relevant[district]["value"]["amount"] if district in relevant else None,
                                   "value_status": relevant[district]["quality"]["value_status"] if district in relevant else "UNKNOWN",
                                   "qualification": relevant[district]["quality"]["qualification"] if district in relevant else "UNAVAILABLE",
                                   "evidence_ids": relevant[district]["evidence_ids"] if district in relevant else local_trace.get(district, {}).get("evidence_ids", []) if metric.startswith("gcis.local") else [],
                                   "reason_codes": relevant[district]["quality"]["reason_codes"] if district in relevant else local_trace.get(district, {}).get("reason_codes", ["GQ_LOCAL_ROW_UNAVAILABLE"]) if metric.startswith("gcis.local") else ["FACTORY_UNAVAILABLE"]}
                                  for district in districts]})

    next_actions.append({"action_id": "CONFIRM_HIRING_CONDITIONS", "rule_id": "HIRING_CONDITIONS_REQUIRED", "district": None})
    for action in next_actions:
        label, reason = ACTION_TEMPLATES[action["action_id"]]
        action.update(label=label, reason=reason)
        # Only registered action IDs become templates, never adapter-provided prose.
        triggers = []
        if action["rule_id"] == "GS03_LOCAL_ACTIVITY":
            triggers = [f for f in ledger.facts if f["metric_id"].startswith("gcis.local") and f["subject"]["district"] == action["district"] and f["value"]["amount"] is not None and Decimal(f["value"]["amount"]) > 0]
        elif action["rule_id"] in {"GS01_CITY_NEW_UP", "GS02_CITY_NEW_DOWN"}:
            triggers = city_facts
        cl = claim("NEXT_ACTION", triggers, rule=action["rule_id"], template="action:" + action["action_id"], required=["CAUSE_UNKNOWN"])
        action["claim_id"] = cl["claim_id"]
    for code in sorted(disclosures):
        claim("LIMITATION", rule="DISCLOSURE_V1", template="disclosure:" + code, required=[code])

    from engine.report_renderer import (TEMPLATE_VERSION, current_render_contract_hash,
                                        default_answer_plan, render_answer_plan)
    content = {"report_id": report_id, "manifest_hash": ledger.manifest_hash,
               "facts": ledger.facts, "claims": claims, "assessments": assessments, "evidence": ledger.evidence,
               "filter_registry": ledger.filter_registry, "metric_groups": metric_groups, "next_actions": next_actions,
               "disclosures": [{"code": code, "text": DISCLOSURES[code]} for code in sorted(disclosures)],
               "template_version": TEMPLATE_VERSION, "render_contract_hash": current_render_contract_hash(), "rules_version": RULES_VERSION}
    content["catalog_hash"] = catalog_digest(content)
    rendered = render_answer_plan(content, default_answer_plan(content))
    content["summary_blocks"] = rendered["blocks"]
    content["render_digest"] = rendered["render_digest"]
    rendered_actions = {b["claim_id"]: b for b in rendered["blocks"] if b["type"] == "claim" and b["heading_id"] == "NEXT_STEPS"}
    for action in content["next_actions"]:
        block = rendered_actions.get(action["claim_id"])
        if block:
            action.update(text=block["text"], evidence_ids=block["evidence_ids"], type="claim")
    return content
