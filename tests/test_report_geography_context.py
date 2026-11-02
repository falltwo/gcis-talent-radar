"""Fixed-scope report follow-ups must not depend on repeated hiring keywords."""
from unittest.mock import patch

import pytest

from agent.report_assistant import answer_report_question
from agent.response_scope import unsupported_geography
from engine.report_renderer import default_answer_plan
from tests.test_report_facts import make_report


@pytest.mark.parametrize("question", [
    "比較臺北市信義區", "比較台北市信義區", "台北市信義區比較",
    "高雄市招募需求", "新北市呢？", "Taipei呢？", "比較板橋區",
])
def test_short_outside_city_followup_is_blocked_before_provider(question):
    report = make_report()
    with patch("agent.report_assistant._provider", return_value=default_answer_plan(report)) as provider:
        result = answer_report_question(report, question)
    assert result["ai_status"] == "BLOCKED"
    provider.assert_not_called()
    assert result["blocks"][0]["type"] == "notice"
    assert "不在本報告涵蓋範圍" in result["blocks"][0]["text"]


@pytest.mark.parametrize("question", [
    "大雅區呢？", "潭子區和大雅區差多少？", "大雅區的台北富邦呢？",
    "潭子區的新竹物流呢？", "這份報告有哪些限制？", "說明每月到職計畫",
])
def test_supported_followup_and_local_company_names_still_reach_provider(question):
    # 明示模型替身；只驗證 scope routing，不宣稱真實模型驗收。
    report = make_report()
    with patch("agent.report_assistant._provider", return_value=default_answer_plan(report)) as provider:
        result = answer_report_question(report, question)
    provider.assert_called_once()
    assert result["ai_status"] == "VERIFIED"


def test_general_chat_keyword_gate_is_unchanged_without_explicit_context():
    assert unsupported_geography("比較臺北市信義區") is False
    assert unsupported_geography("比較臺北市信義區", hiring_context=True) is True
    assert unsupported_geography("臺北市信義區職缺") is True


def test_explicit_context_preserves_local_company_name_disambiguation():
    for question in ["台中大雅區的台北富邦", "臺中潭子區的新竹物流"]:
        assert unsupported_geography(question, hiring_context=True) is False
