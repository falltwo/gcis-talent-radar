"""Official-report contract tests. All numeric observations here are synthetic."""
from copy import deepcopy

import pytest

from engine.claim_builder import build_report_content
from engine.fact_ledger import digest
from engine.report_renderer import PlanValidationError, default_answer_plan, render_answer_plan


def report_inputs():
    scenario = {"schema_version": "1.0", "districts": ["大雅區", "潭子區", "神岡區"],
                "manufacturing": {"division_code": "29", "classification_version": "mfg-divisions-v1"},
                "occupation": {"type": "KEYWORD", "keyword": "CNC", "retrieval_profile_version": "job-rules-v1"},
                "observation": {"mode": "LATEST_AVAILABLE", "month": None, "window_months": 3, "knowledge_cutoff": None},
                "hiring_plan": {"net_hires": 31, "start_month": "2026-11", "end_month": "2027-01"}}
    jobs = {"available": True, "snapshot_date": "2026-10-05", "industry_id": "IND_MFG", "occupation_keyword": "CNC", "comparisons": []}
    for district, postings, workers in (("大雅區", 10, 100), ("潭子區", 20, 50), ("神岡區", 0, 0)):
        jobs["comparisons"].append({"district": district, "vacancy_postings": postings, "requested_workers": workers,
                                    "distinct_companies": postings, "coverage_status": "OBSERVED_SNAPSHOT_COMPLETE_WITHIN_QUERY_LIMIT",
                                    "limit_reached_districts": [], "evidence": {"data_period": "2026-10-05", "geography": district}})
    city_rows = [{"year_month": f"{year}-{month:02}", "new_company_count": value}
                 for year, value in ((2024, 10), (2025, 20)) for month in range(1, 13)]
    gcis = {"available": True, "city": {"available": True, "start": "2025-01", "end": "2025-12", "current_sum": 240,
            "baseline_start": "2024-01", "baseline_end": "2024-12", "baseline_sum": 120, "monthly_rows": city_rows, "evidence": {}},
            "local": [{"district": "大雅區", "industry_code": "29", "start": "2025-10", "end": "2025-12", "available": True,
                       "new_company_count": 3, "capital_increase_company_count": None, "dissolved_company_count": None,
                       "qualification": "PARTIAL", "reason_codes": ["GQ_CLASSIFIED_SAMPLE_NOT_POPULATION"], "evidence": {}}]}
    background = {"wage": {"available": True, "data_period": "11412", "average_insured_salary": 36201.78, "evidence": {}},
                  "factories": [{"district": "大雅區", "available": True, "factory_count": 30, "period": "2025-12", "evidence": {}}]}
    return scenario, {"sources": [], "manifest_hash": "a" * 64}, jobs, gcis, {}, background


def make_report(**overrides):
    args = report_inputs()
    names = ("scenario", "manifest", "jobs", "gcis", "planning", "background")
    values = {name: value for name, value in zip(names, args)}
    values.update(overrides)
    report = build_report_content("rep_fixture", **values)
    report["scenario"] = values["scenario"]
    return report


def test_report_has_bound_facts_correct_units_and_monthly_plan():
    report = make_report()
    assert report["catalog_hash"]
    for fact in report["facts"]:
        assert fact["report_id"] == "rep_fixture"
        assert fact["manifest_hash"] == "a" * 64
        assert fact["selection"]["filter_spec_id"] in report["filter_registry"]
    plans = [f for f in report["facts"] if f["data_kind"] == "USER_PLAN"]
    assert [f["value"]["amount"] for f in plans] == ["11", "10", "10"]
    assert any("平均投保薪資" in b["text"] and "36,201.78" in b["text"] for b in report["summary_blocks"])
    assert any(f["metric_id"] == "factory.registered_factories" for f in report["facts"])
    rendered = render_answer_plan(report, default_answer_plan(report))
    assert rendered["render_digest"] == report["render_digest"]


def test_public_postings_and_worker_rankings_have_separate_roles():
    report = make_report()
    plan = default_answer_plan(report, question="比較差額")
    text = "\n".join(b["text"] for b in render_answer_plan(report, plan)["blocks"])
    assert "潭子區的可觀測刊登職缺比大雅區多 10 筆" in text
    assert "大雅區的可觀測刊登需求人數比潭子區多 50 人" in text


def test_one_capped_district_disables_whole_row_ranking():
    scenario, manifest, jobs, gcis, planning, background = report_inputs()
    jobs["comparisons"][0]["coverage_status"] = "QUERY_LIMIT_REACHED"
    jobs["comparisons"][0]["limit_reached_districts"] = ["大雅區"]
    report = make_report(jobs=jobs)
    assert not [c for c in report["claims"] if c["type"] in {"COMPARISON", "DIFFERENCE"}]
    assert report["metric_groups"][0]["rows"][0]["value_status"] == "LOWER_BOUND"
    assert any(d["code"] == "QUERY_LIMIT_REACHED" for d in report["disclosures"])


@pytest.mark.parametrize("mutation", ["district", "period", "keyword", "industry", "missing", "negative", "fraction", "bool"])
def test_invalid_job_scope_or_quantity_does_not_become_supported_fact(mutation):
    _, _, jobs, _, _, _ = report_inputs()
    if mutation == "district": jobs["comparisons"][0]["district"] = "西屯區"
    elif mutation == "period": jobs["comparisons"][0]["evidence"]["data_period"] = "2026-09-05"
    elif mutation == "keyword": jobs["occupation_keyword"] = "軟體"
    elif mutation == "industry": jobs["industry_id"] = "IND_ICT"
    elif mutation == "missing": jobs["comparisons"].pop()
    elif mutation == "negative": jobs["comparisons"][0]["requested_workers"] = -1
    elif mutation == "fraction": jobs["comparisons"][0]["requested_workers"] = 0.5
    else: jobs["comparisons"][0]["requested_workers"] = True
    report = make_report(jobs=jobs)
    assert not any(f["metric_id"] == "jobs.requested_workers" and f["subject"]["district"] == "大雅區" for f in report["facts"])
    assert not any(c["type"] == "COMPARISON" and any(next(f for f in report["facts"] if f["fact_id"] == fid)["metric_id"] == "jobs.requested_workers" for fid in c["fact_refs"]) for c in report["claims"])


def test_true_zero_is_preserved_and_unknown_local_is_not_zero():
    report = make_report()
    true_zero = next(f for f in report["facts"] if f["metric_id"] == "jobs.requested_workers" and f["subject"]["district"] == "神岡區")
    assert true_zero["value"]["amount"] == "0" and true_zero["quality"]["value_status"] == "EXACT_WITHIN_SCOPE"
    group = next(g for g in report["metric_groups"] if g["metric_id"] == "gcis.local_capital_increase_companies")
    assert all(r["value"] is None for r in group["rows"])


def test_gcis_ablation_changes_claims_and_actions_but_never_jobs_or_plan():
    with_gcis = make_report()
    without = make_report(gcis={"available": False})
    select = lambda r: [(f["metric_id"], f["subject"], f["period"], f["value"]) for f in r["facts"] if f["metric_id"].startswith(("jobs.", "plan."))]
    assert select(with_gcis) == select(without)
    assert any(c["rule_id"] == "GS01_CITY_NEW_UP" for c in with_gcis["claims"])
    assert not any(c["rule_id"] == "GS01_CITY_NEW_UP" for c in without["claims"])
    assert {a["action_id"] for a in with_gcis["next_actions"]} != {a["action_id"] for a in without["next_actions"]}


def test_city_gap_or_inconsistent_total_cannot_create_direction_claim():
    _, _, _, gcis, _, _ = report_inputs()
    gcis["city"]["monthly_rows"].pop()
    report = make_report(gcis=gcis)
    assert not any(c["type"] == "PERIOD_CHANGE" for c in report["claims"])
    _, _, _, gcis, _, _ = report_inputs()
    gcis["city"]["current_sum"] = 241
    assert not any(c["type"] == "PERIOD_CHANGE" for c in make_report(gcis=gcis)["claims"])


def test_partial_undefined_sample_zero_never_creates_zero_fact():
    _, _, _, gcis, _, _ = report_inputs()
    gcis["local"][0]["new_company_count"] = 0
    report = make_report(gcis=gcis)
    unknown = next(f for f in report["facts"] if f["metric_id"] == "gcis.local_new_companies")
    assert unknown["value"]["kind"] == "UNKNOWN" and unknown["value"]["amount"] is None
    assert not any(c["type"] == "OBSERVATION" and unknown["fact_id"] in c["fact_refs"] for c in report["claims"])
    gcis["local"][0]["evidence"] = {"per_event_status": {"setup": {"available": True}}}
    report = make_report(gcis=gcis)
    assert next(f for f in report["facts"] if f["metric_id"] == "gcis.local_new_companies")["quality"]["value_status"] == "SAMPLE_MATCH_ZERO"


@pytest.mark.parametrize("field,new_value", [("unit", "posting"), ("subject", {"city": "臺中市", "district": "西屯區", "geography_role": "WORK_LOCATION"}),
                                               ("data_kind", "FORECAST"), ("value", {"kind": "COUNT", "amount": "999", "lower": None, "upper": None})])
def test_saved_catalog_mutations_fail_closed(field, new_value):
    report = make_report()
    plan = default_answer_plan(report)
    target = next(f for f in report["facts"] if f["metric_id"] == "jobs.requested_workers")
    target[field] = new_value
    with pytest.raises(PlanValidationError): render_answer_plan(report, plan)


def test_planning_distribution_cannot_override_confirmed_scenario():
    with pytest.raises(ValueError, match="PLANNING_DISTRIBUTION_MISMATCH"):
        make_report(planning={"monthly_targets": [{"month": "2026-11", "people": 99}]})


def test_filter_registry_retains_expression_and_order_and_boolean_operator():
    report = make_report()
    for fact in report["facts"]:
        record = report["filter_registry"][fact["selection"]["filter_spec_id"]]
        assert record["filter_digest"] == digest(record["spec"])
    assert digest({"op": "AND", "args": ["a", "b"]}) != digest({"op": "OR", "args": ["a", "b"]})


def test_mandatory_disclosures_survive_model_selecting_only_plans():
    report = make_report()
    cid = next(c["claim_id"] for c in report["claims"] if c["type"] == "USER_PLAN")
    plan = {"report_id": report["report_id"], "catalog_hash": report["catalog_hash"], "sections": [{"heading_id": "HIRING_PLAN", "claim_ids": [cid]}]}
    blocks = render_answer_plan(report, plan)["blocks"]
    assert {b["code"] for b in blocks if b["type"] == "disclosure"} == {d["code"] for d in report["disclosures"]}


def test_retained_evidence_preserves_structured_source_provenance():
    _, _, _, gcis, _, _ = report_inputs()
    details = {"source_release": "release-fixture", "classification": {"mapping_version": "tax-fixture-v1", "historical": False},
               "qualification": "PARTIAL", "reason_codes": ["GQ_CURRENT_LABEL_RETROSPECTIVE"],
               "capital_state_observations": [{"baseline_date": "2025-10-01", "current_state_date": "2025-12-01", "source_row_refs": ["row-1"]}],
               "row_locator": {"source_file": "fixture.csv", "rows": [1, 4]},
               "limitations": ["目前分類標籤回看；不能推論當時已知資訊。"]}
    gcis["local"][0]["evidence"] = deepcopy(details)
    report = make_report(gcis=gcis)
    fact = next(f for f in report["facts"] if f["metric_id"] == "gcis.local_new_companies")
    evidence = next(e for e in report["evidence"] if e["evidence_id"] == fact["evidence_ids"][0])
    assert evidence["source_details"] == details
    assert evidence["classification"]["mapping_version"] == "tax-fixture-v1"
    assert evidence["row_locator"]["rows"] == [1, 4]
    assert evidence["capital_state_observations"][0]["source_row_refs"] == ["row-1"]


def test_zero_city_baseline_has_absolute_difference_without_percent():
    _, _, _, gcis, _, _ = report_inputs()
    gcis["city"]["baseline_sum"] = 0
    for row in gcis["city"]["monthly_rows"]:
        if row["year_month"].startswith("2024"):
            row["new_company_count"] = 0
    report = make_report(gcis=gcis)
    assert not any(c["type"] == "PERIOD_CHANGE" for c in report["claims"])
    assert any(c["type"] == "DIFFERENCE" and c["rule_id"] == "GS01_CITY_NEW_UP" for c in report["claims"])
    assert any("基期為零不計算百分比" in b["text"] for b in report["summary_blocks"])


def test_unequal_city_windows_cannot_create_change_claim():
    _, _, _, gcis, _, _ = report_inputs()
    gcis["city"].update(start="2025-07", baseline_end="2025-06", current_sum=120, baseline_sum=240)
    assert not any(c["type"] == "PERIOD_CHANGE" for c in make_report(gcis=gcis)["claims"])


def test_pinned_job_snapshot_cannot_be_silently_replaced_by_latest():
    report = make_report(manifest={"manifest_hash": "a" * 64, "resolved_periods": {"jobs": "2026-09-05"}})
    assert not any(f["metric_id"].startswith("jobs.") for f in report["facts"])


def test_wage_keeps_manufacturing_and_employee_insurance_scope():
    report = make_report()
    wage = next(f for f in report["facts"] if f["metric_id"] == "wage.average_insured_salary")
    spec = report["filter_registry"][wage["selection"]["filter_spec_id"]]["spec"]
    assert spec["expression"]["op"] == "AND"
    filters = {item["field"]: item["value"] for item in spec["expression"]["args"]}
    assert filters == {"region_code": "66", "industry_code": "C", "unit_type_code": "1", "employment_insurance_code": "1"}
    assert wage["value"]["amount"] == "36201.78"
    assert any("全市製造業產業勞工（參加就保口徑）平均投保薪資" in b["text"] for b in report["summary_blocks"])


def test_unavailable_local_rows_keep_unknown_facts_and_clickable_evidence():
    _, _, _, gcis, _, _ = report_inputs()
    local = gcis["local"][0]
    local.update(available=False, qualification="UNAVAILABLE", new_company_count=None,
                 reason_codes=["GQ_CLASSIFICATION_UNAVAILABLE", "GQ_LOCAL_SOURCE_INCOMPLETE"])
    details = {"classification": {"available": False, "mapping_version": "missing-fixture"},
               "reason_codes": local["reason_codes"], "per_event_status": {"setup": {"available": False, "missing_or_invalid_months": ["2025-10"]}}}
    local["evidence"] = details
    report = make_report(gcis=gcis)
    facts = [f for f in report["facts"] if f["metric_id"].startswith("gcis.local")]
    assert len(facts) == 3
    for fact in facts:
        assert fact["value"] == {"kind": "UNKNOWN", "amount": None, "lower": None, "upper": None}
        assert fact["quality"]["qualification"] == "UNAVAILABLE"
        assert fact["quality"]["comparison_status"] == "NOT_COMPARABLE"
        evidence = next(e for e in report["evidence"] if e["evidence_id"] in fact["evidence_ids"])
        assert evidence["source_details"] == details
        assert not any(c["type"] == "OBSERVATION" and fact["fact_id"] in c["fact_refs"] for c in report["claims"])
    for group in report["metric_groups"]:
        if not group["metric_id"].startswith("gcis.local"):
            continue
        row = group["rows"][0]
        assert row["fact_id"] and row["evidence_ids"]
        assert row["value"] is None and row["value_status"] == "UNKNOWN"
        assert "GQ_CLASSIFICATION_UNAVAILABLE" in row["reason_codes"]
    assert any(b["evidence_ids"] and "目前未知" in b["text"] for b in report["summary_blocks"])


def test_unavailable_local_invalid_period_retains_evidence_without_false_dated_fact():
    _, _, _, gcis, _, _ = report_inputs()
    gcis["local"][0].update(available=False, start=None, end=None, reason_codes=["GQ_LOCAL_SOURCE_INCOMPLETE"])
    report = make_report(gcis=gcis)
    assert not any(f["metric_id"].startswith("gcis.local") for f in report["facts"])
    group = next(g for g in report["metric_groups"] if g["metric_id"] == "gcis.local_new_companies")
    row = group["rows"][0]
    assert row["fact_id"] is None and row["value"] is None and row["evidence_ids"]
    assert "GQ_LOCAL_PERIOD_UNAVAILABLE" in row["reason_codes"]


def test_rendered_city_prefix_and_disclosures_avoid_development_terms():
    report = make_report()
    text = "\n".join(b["text"] for b in report["summary_blocks"])
    assert "臺中市全市的全市" not in text
    assert "MVP" not in text
    assert "臺中市全市新設公司" in text


@pytest.mark.parametrize("field,value", [("render_contract_hash", "f" * 64), ("template_version", "renderer-future")])
def test_renderer_contract_metadata_changes_fail_closed(field, value):
    report = make_report()
    plan = default_answer_plan(report)
    report[field] = value
    with pytest.raises(PlanValidationError, match="RENDER_CONTRACT_INCOMPATIBLE"):
        render_answer_plan(report, plan)


def test_renderer_contract_is_included_in_catalog_digest():
    from engine.claim_builder import catalog_digest
    report = make_report()
    original = report["catalog_hash"]
    report["render_contract_hash"] = "f" * 64
    assert catalog_digest(report) != original


def test_current_registry_edits_cannot_reinterpret_saved_report(monkeypatch):
    from engine.fact_ledger import DISCLOSURES, METRICS
    from engine.report_renderer import current_render_contract_hash
    report = make_report()
    original_blocks = deepcopy(report["summary_blocks"])
    original_hash = report["render_contract_hash"]
    monkeypatch.setitem(DISCLOSURES, "CAUSE_UNKNOWN", "未來版本的限制文字")
    assert current_render_contract_hash() != original_hash
    with pytest.raises(PlanValidationError, match="RENDER_CONTRACT_INCOMPATIBLE"):
        render_answer_plan(report, default_answer_plan(report))
    assert report["summary_blocks"] == original_blocks


def test_actual_renderer_source_fingerprint_change_rejects_old_catalog(monkeypatch):
    import engine.report_renderer as renderer
    report = make_report()
    old_read = renderer.Path.read_bytes
    monkeypatch.setattr(renderer.Path, "read_bytes", lambda path: old_read(path) + b"\n# future renderer change\n")
    with pytest.raises(PlanValidationError, match="RENDER_CONTRACT_INCOMPATIBLE"):
        render_answer_plan(report, default_answer_plan(report))


def test_ranking_limit_question_focuses_on_at_most_two_gaps_and_two_actions():
    report = make_report()
    plan = default_answer_plan(report, question="為什麼有些數字不能排名？")
    assert {s["heading_id"] for s in plan["sections"]} <= {"EVIDENCE_GAPS", "NEXT_STEPS"}
    assert all(len(s["claim_ids"]) <= 2 for s in plan["sections"])
    rendered = render_answer_plan(report, plan)
    assert sum(b["type"] == "claim" for b in rendered["blocks"]) <= 4
    assert {b["code"] for b in rendered["blocks"] if b["type"] == "disclosure"} == {d["code"] for d in report["disclosures"]}


def test_planning_and_gcis_questions_select_only_their_registered_sections():
    report = make_report()
    plan = default_answer_plan(report, question="我的計畫每月目標如何分配？")
    assert [s["heading_id"] for s in plan["sections"]] == ["HIRING_PLAN"]
    plan = default_answer_plan(report, question="請說明GCIS與同業公司資料")
    assert {s["heading_id"] for s in plan["sections"]} <= {"GCIS_CONTEXT", "EVIDENCE_GAPS"}
    assert any(s["heading_id"] == "GCIS_CONTEXT" for s in plan["sections"])


def test_default_summary_and_comparison_focus_deduplicate_operand_pairs():
    report = make_report()
    catalog = {c["claim_id"]: c for c in report["claims"]}
    for question in ("", "比較哪區需求較多？"):
        plan = default_answer_plan(report, question=question)
        selected = [catalog[cid] for section in plan["sections"] for cid in section["claim_ids"]]
        pairs = [tuple(sorted(c["operands"].values())) for c in selected if c["type"] in {"COMPARISON", "DIFFERENCE"}]
        assert len(pairs) == len(set(pairs))
        assert not any(c["type"] == "COMPARISON" for c in selected)
        if question:
            assert [s["heading_id"] for s in plan["sections"]] == ["PUBLIC_JOB_OBSERVATIONS"]
            assert all(c["type"] == "DIFFERENCE" for c in selected)
