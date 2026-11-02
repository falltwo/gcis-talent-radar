"""Controlled ID planning and fault handling, with no paid provider calls."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from agent.report_assistant import answer_report_question
from engine.report_renderer import default_answer_plan, render_answer_plan
from tests.test_report_facts import make_report


def test_valid_provider_plan_uses_only_server_rendered_words():
    report = make_report()
    plan = default_answer_plan(report)
    result = answer_report_question(report, "請解釋這份報告", provider=lambda request: plan)
    assert result["ai_status"] == "VERIFIED"
    assert result["blocks"] == render_answer_plan(report, plan)["blocks"]
    assert len({e["request_id"] for e in result["events"]}) == 1
    assert len({e["event_id"] for e in result["events"]}) == len(result["events"])


@pytest.mark.parametrize("mutation", ["text", "value", "unit", "heading", "unknown", "cross_report", "old_catalog", "duplicate", "citation"])
def test_model_cannot_smuggle_unapproved_prose_scope_values_or_citations(mutation):
    report = make_report()
    plan = deepcopy(default_answer_plan(report))
    malicious = "潭子人才充足，放心擴廠999人"
    if mutation == "text": plan["sections"][0]["text"] = malicious
    elif mutation in {"value", "unit", "citation"}: plan[mutation] = malicious
    elif mutation == "heading": plan["sections"][0]["heading_id"] = malicious
    elif mutation == "unknown": plan["sections"][0]["claim_ids"][0] = "cl_some_other_report"
    elif mutation == "cross_report": plan["report_id"] = "rep_other"
    elif mutation == "old_catalog": plan["catalog_hash"] = "f" * 64
    else: plan["sections"][0]["claim_ids"].append(plan["sections"][0]["claim_ids"][0])
    calls = []
    def provider(request):
        calls.append(request)
        return plan
    result = answer_report_question(report, "請解釋這份報告", provider=provider)
    assert result["ai_status"] == "FALLBACK" and len(calls) == 2
    assert malicious not in json.dumps(result, ensure_ascii=False)
    assert calls[0]["catalog_hash"] == calls[1]["catalog_hash"] == report["catalog_hash"]
    assert calls[1]["previous_error_code"]


def test_retry_accepts_corrected_plan_without_relaxing_catalog():
    report = make_report()
    plans = iter([{"text": "自編敘述"}, default_answer_plan(report)])
    result = answer_report_question(report, "比較需求人數", provider=lambda request: next(plans))
    assert result["ai_status"] == "VERIFIED"
    assert sum(e["outcome"] == "MODEL_ATTEMPT" for e in result["events"]) == 2


def test_misplaced_real_claim_id_cannot_launder_it_into_another_heading():
    report = make_report()
    cid = next(c["claim_id"] for c in report["claims"] if c["type"] == "USER_PLAN")
    plan = {"report_id": report["report_id"], "catalog_hash": report["catalog_hash"],
            "sections": [{"heading_id": "PUBLIC_JOB_OBSERVATIONS", "claim_ids": [cid]}]}
    assert answer_report_question(report, "請解釋", provider=lambda request: plan)["ai_status"] == "FALLBACK"


@pytest.mark.parametrize("question", ["西屯區的需求如何", "台北市信義區有多少職缺", "這裡保證能招到31人嗎", "招募時只錄取35歲以下男性", ""])
def test_scope_and_governance_rejections_never_call_provider(question):
    report = make_report()
    with patch("agent.report_assistant._provider") as provider:
        result = answer_report_question(report, question)
    provider.assert_not_called()
    assert result["ai_status"] == "BLOCKED"
    assert result["blocks"][0]["type"] == "notice"


def test_no_key_or_provider_error_returns_useful_deterministic_report():
    report = make_report()
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}):
        result = answer_report_question(report, "請解釋這份報告")
    assert result["ai_status"] == "FALLBACK"
    assert any(b["type"] == "claim" for b in result["blocks"])
    assert "PROVIDER_NOT_CONFIGURED" not in result["answer"]


def test_openrouter_text_must_be_strict_json_without_duplicate_keys():
    report = make_report()
    payload = {"choices": [{"message": {"content": '{"report_id":"a","report_id":"b"}'}}]}
    result = answer_report_question(report, "請解釋", provider=lambda request: payload)
    assert result["ai_status"] == "FALLBACK"


def test_question_events_use_different_request_ids_for_followups():
    report = make_report()
    provider = lambda request: default_answer_plan(report)
    first = answer_report_question(report, "請解釋", provider=provider)
    second = answer_report_question(report, "再解釋", provider=provider)
    assert first["request_id"] != second["request_id"]
    assert first["report_id"] == second["report_id"]
    assert first["catalog_hash"] == second["catalog_hash"]


def test_unknown_provider_error_text_is_not_exposed_or_audited():
    report = make_report()
    secret = "fake-provider-secret-123456"
    def provider(request): raise RuntimeError(secret)
    result = answer_report_question(report, "請解釋", provider=provider)
    assert result["ai_status"] == "FALLBACK"
    assert secret not in json.dumps(result)


def test_provider_usage_and_versions_are_logged_without_raw_question():
    report = make_report()
    question = "請解釋這份報告的證據"
    payload = {"model": "provider-approved-fixture", "usage": {"prompt_tokens": 20, "completion_tokens": 10, "secret": "drop-me"},
               "choices": [{"message": {"content": json.dumps(default_answer_plan(report))}}]}
    result = answer_report_question(report, question, provider=lambda request: payload)
    ev = next(e for e in result["events"] if e["outcome"] == "PROVIDER_RESPONSE")
    assert ev["actual_model"] == "provider-approved-fixture"
    assert ev["token_usage"] == {"prompt_tokens": 20, "completion_tokens": 10}
    assert ev["manifest_hash"] == report["manifest_hash"] and ev["prompt_version"]
    assert question not in json.dumps(result["events"], ensure_ascii=False)


def test_incompatible_old_renderer_contract_never_calls_model():
    from engine.report_renderer import PlanValidationError
    report = make_report()
    report["render_contract_hash"] = "0" * 64
    with patch("agent.report_assistant._provider") as provider:
        with pytest.raises(PlanValidationError, match="RENDER_CONTRACT_INCOMPATIBLE"):
            answer_report_question(report, "請解釋這份舊報告")
    provider.assert_not_called()


@pytest.mark.parametrize("payload", [
    {"choices": [None], "unverified_text": "不可信provider原文"},
    {"choices": [{"message": "不可信provider原文"}]},
    {"choices": [{"message": {"content": "不可信provider原文"}}], "usage": "不可信provider原文"},
])
def test_malformed_provider_envelopes_fall_back_without_exposing_original_text(payload):
    report = make_report()
    calls = []
    def provider(request):
        calls.append(request)
        return payload
    result = answer_report_question(report, "請解釋這份報告", provider=provider)
    assert result["ai_status"] == "FALLBACK"
    assert len(calls) == 2
    assert result["blocks"] == render_answer_plan(report, default_answer_plan(report))["blocks"]
    assert "不可信provider原文" not in json.dumps(result, ensure_ascii=False)
    assert sum(e["outcome"] == "MODEL_OR_PLAN_REJECTED" for e in result["events"]) == 2


@pytest.mark.parametrize("usage", ["untrusted-usage", [1], 42, None])
def test_bad_optional_usage_does_not_reject_a_valid_evidence_bound_plan(usage):
    report = make_report()
    plan = default_answer_plan(report)
    payload = {"choices": [{"message": {"content": json.dumps(plan)}}], "usage": usage}
    result = answer_report_question(report, "請解釋這份報告", provider=lambda request: payload)
    assert result["ai_status"] == "VERIFIED"
    assert result["blocks"] == render_answer_plan(report, plan)["blocks"]
    response_event = next(e for e in result["events"] if e["outcome"] == "PROVIDER_RESPONSE")
    assert response_event["token_usage"] == {}
    assert "untrusted-usage" not in json.dumps(result)
