import json
from unittest.mock import patch

import pytest
import requests

from agent.llm_agent import OpenRouterAgent
from agent.policy_guard import DEFAULT_MODEL, evaluate_fair_hiring


class FakeResponse:
    ok = True

    def __init__(self, content, status_code=200):
        self._content = content
        self.status_code = status_code

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def structured_response(*, violation, category):
    return FakeResponse(json.dumps({
        "violation": violation,
        "category": category,
        "rationale": "This private rationale must not be retained.",
    }))


@pytest.fixture
def audit_path(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AGENT_AUDIT_LOG_PATH", str(path))
    return path


def test_policy_guard_uses_configured_model_and_returns_violation_without_rationale(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("GUARD_MODEL", "openai/gpt-oss-safeguard-20b")
    response = structured_response(violation=True, category="年齡")
    with patch("agent.policy_guard.requests.post", return_value=response) as post:
        result = evaluate_fair_hiring("招募時只考慮三十五歲以下")

    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "openai/gpt-oss-safeguard-20b"
    assert payload["temperature"] == 0
    assert payload["max_tokens"] <= 384
    assert payload["response_format"]["type"] == "json_schema"
    assert post.call_args.kwargs["timeout"] == 5
    assert result["called"] is True
    assert result["decision"] == "VIOLATION"
    assert result["category"] == "年齡"
    assert "rationale" not in result
    assert result["latency_ms"] >= 0


def test_policy_guard_allow_verdict_is_validated(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch("agent.policy_guard.requests.post", return_value=structured_response(
        violation=False, category="none"
    )):
        result = evaluate_fair_hiring("女性應徵者的面試通過率是多少")
    assert result["decision"] == "ALLOW"
    assert result["category"] == "none"


@pytest.mark.parametrize("content,expected_status", [
    ("not json", "INVALID_RESPONSE"),
    (json.dumps({"violation": "false", "category": "none", "rationale": "bad type"}), "INVALID_SCHEMA"),
    (json.dumps({"violation": False, "category": "none", "rationale": "ok", "extra": 1}), "INVALID_SCHEMA"),
])
def test_policy_guard_malformed_response_fails_open(monkeypatch, content, expected_status):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch("agent.policy_guard.requests.post", return_value=FakeResponse(content)):
        result = evaluate_fair_hiring("台中製造業女性員工比例")
    assert result["called"] is True
    assert result["decision"] == "FAIL_OPEN"
    assert result["status"] == expected_status


def test_policy_guard_timeout_fails_open(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch("agent.policy_guard.requests.post", side_effect=requests.Timeout):
        result = evaluate_fair_hiring("女性應徵者的面試通過率是多少")
    assert result["decision"] == "FAIL_OPEN"
    assert result["status"] == "TIMEOUT"


def test_policy_guard_skips_when_api_key_is_missing(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with patch("agent.policy_guard.requests.post") as post:
        result = evaluate_fair_hiring("女性應徵者的面試通過率是多少")
    post.assert_not_called()
    assert result == {
        "called": False,
        "status": "SKIPPED_NO_API_KEY",
        "decision": "SKIPPED",
        "category": "none",
        "latency_ms": 0,
    }


def test_rule_rejection_precedes_policy_guard_and_answer_model(audit_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch("agent.llm_agent.evaluate_fair_hiring") as guard, \
         patch("agent.llm_agent._post_chat") as answer_model:
        result = OpenRouterAgent().process_query("招募時只錄取男性")

    guard.assert_not_called()
    answer_model.assert_not_called()
    assert result["status"] == "REJECTED"
    event = json.loads(audit_path.read_text(encoding="utf-8"))
    assert event["policy_guard"]["called"] is False
    assert event["policy_guard"]["status"] == "NOT_CALLED_RULE_REJECTED"


@pytest.mark.parametrize("query", [
    "招募時幫我篩掉家裡有小孩的應徵者",
    "招募時不要有生理期困擾的人",
])
def test_second_guard_catches_rule_miss_in_hiring_context(audit_path, monkeypatch, query):
    from agent.prompt_guard import inspect_hiring_prompt

    rule_result = inspect_hiring_prompt(query)
    assert rule_result["decision"] == "ALLOW"
    assert rule_result["hiring_context"] is True
    assert rule_result["matched_traits"] == []

    guard_result = {
        "called": True,
        "status": "OK",
        "decision": "VIOLATION",
        "category": "育兒",
        "latency_ms": 12.3,
    }
    with patch("agent.llm_agent.evaluate_fair_hiring", return_value=guard_result) as guard, \
         patch("agent.llm_agent._post_chat") as answer_model:
        result = OpenRouterAgent().process_query(query)

    guard.assert_called_once_with(query)
    answer_model.assert_not_called()
    assert result["status"] == "REJECTED"
    assert result["intent"] == "FAIR_HIRING_POLICY"
    assert result["governance"]["policy_guard"]["decision"] == "VIOLATION"
    event = json.loads(audit_path.read_text(encoding="utf-8"))
    assert event["policy_guard"]["called"] is True
    assert query not in audit_path.read_text(encoding="utf-8")


def test_neutral_employee_demographic_query_reaches_guard_and_is_not_rejected(audit_path):
    query = "台中製造業員工年齡分布如何？"
    guard_result = {
        "called": True,
        "status": "OK",
        "decision": "ALLOW",
        "category": "none",
        "latency_ms": 15.0,
    }
    with patch("agent.llm_agent.evaluate_fair_hiring", return_value=guard_result) as guard, \
         patch("agent.llm_agent._post_chat", return_value={
             "choices": [{"message": {"content": "目前沒有可引用的資料。"}}]
         }) as answer_model:
        result = OpenRouterAgent().process_query(query)

    guard.assert_called_once_with(query)
    answer_model.assert_called_once()
    assert result["status"] != "REJECTED"
    assert result["governance"]["policy_guard"]["decision"] == "ALLOW"


def test_age_distribution_without_hiring_decision_does_not_call_guard(audit_path):
    query = "年齡分布如何？"
    with patch("agent.llm_agent.evaluate_fair_hiring") as guard, \
         patch("agent.llm_agent._post_chat", return_value={
             "choices": [{"message": {"content": "目前沒有可引用的資料。"}}]
         }):
        result = OpenRouterAgent().process_query(query)

    guard.assert_not_called()
    assert result["status"] == "REJECTED"
    assert result["intent"] == "OUT_OF_SCOPE"


def test_ordinary_job_query_does_not_call_policy_guard(audit_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with patch("agent.llm_agent.evaluate_fair_hiring") as guard, \
         patch("agent.llm_agent._post_chat", return_value={
             "choices": [{"message": {"content": "尚無資料"}}]
         }) as answer_model:
        result = OpenRouterAgent().process_query("大雅區機械相關職缺有多少？")

    guard.assert_not_called()
    answer_model.assert_called_once()
    assert result["governance"]["policy_guard"]["called"] is False
    event = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert event["policy_guard"]["status"] == "NOT_CALLED_NOT_ELIGIBLE"


def test_guard_violation_rejects_before_answer_model_and_audit_has_no_prompt_or_reasoning(audit_path, monkeypatch):
    query = "女性應徵者的面試通過率是多少"
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    guard_result = {
        "called": True,
        "status": "OK",
        "decision": "VIOLATION",
        "category": "性別／性別認同",
        "latency_ms": 321.4,
        "rationale": "Private model rationale must never be returned or logged.",
    }
    with patch("agent.llm_agent.evaluate_fair_hiring", return_value=guard_result), \
         patch("agent.llm_agent._post_chat") as answer_model:
        result = OpenRouterAgent().process_query(query)

    answer_model.assert_not_called()
    assert result["status"] == "REJECTED"
    assert result["intent"] == "FAIR_HIRING_POLICY"
    assert result["governance"]["policy_guard"]["decision"] == "VIOLATION"
    event_text = audit_path.read_text(encoding="utf-8")
    event = json.loads(event_text)
    assert event["policy_guard"] == {
        "called": True,
        "status": "OK",
        "decision": "VIOLATION",
        "category": "性別／性別認同",
        "latency_ms": 321.4,
    }
    assert query not in event_text
    assert "Private model rationale" not in event_text


@pytest.mark.parametrize("guard_result", [
    {"called": True, "status": "OK", "decision": "ALLOW", "category": "none", "latency_ms": 100},
    {"called": True, "status": "TIMEOUT", "decision": "FAIL_OPEN", "category": "none", "latency_ms": 5000},
    {"called": False, "status": "SKIPPED_NO_API_KEY", "decision": "SKIPPED", "category": "none", "latency_ms": 0},
])
def test_nonviolating_or_unavailable_guard_allows_answer_model(audit_path, guard_result):
    query = "女性應徵者的面試通過率是多少"
    with patch("agent.llm_agent.evaluate_fair_hiring", return_value=guard_result), \
         patch("agent.llm_agent._post_chat", return_value={
             "choices": [{"message": {"content": "沒有工具資料"}}]
         }) as answer_model:
        result = OpenRouterAgent().process_query(query)

    answer_model.assert_called_once()
    assert result["status"] == "FAILED"  # Main answer still needs tool evidence.
    assert result["governance"]["policy_guard"]["decision"] == guard_result["decision"]
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert events[0]["policy_guard"]["status"] == guard_result["status"]
    assert all("rationale" not in event["policy_guard"] for event in events)
