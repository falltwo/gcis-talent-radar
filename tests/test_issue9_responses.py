"""Issue #9 points 4–6: response semantics, not provider wording."""
from unittest.mock import patch
import json

import pytest

from agent.llm_agent import OpenRouterAgent
from agent.response_scope import unsupported_geography, vacancy_comparison


@pytest.fixture(autouse=True)
def audit_path(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))


@pytest.mark.parametrize("query", ["台北市信義區有多少職缺？", "台北大安區和台中大雅區比職缺", "新北市板橋區缺工", "信義區職缺"])
def test_geographic_no_data_never_calls_provider_or_tool(query):
    with patch("agent.llm_agent._post_chat") as model, patch("agent.llm_agent.execute_tool") as tool:
        result = OpenRouterAgent().process_query(query)
    assert result['status'] == 'NO_DATA'
    assert '沒有' in result['answer'] and '替代' in result['answer']
    assert result['tool_calls'] == [] and result['evidence'] == {}
    model.assert_not_called()
    tool.assert_not_called()


@pytest.mark.parametrize("query, intent", [("今天天氣如何？", "OUT_OF_SCOPE"), ("台中今天天氣如何？", "OUT_OF_SCOPE"), ("幫我只招男生的作業員", "FAIR_HIRING_POLICY")])
def test_rejection_has_own_response(query, intent):
    with patch('agent.llm_agent._post_chat') as model:
        result = OpenRouterAgent().process_query(query)
    assert result['status'] == 'REJECTED'
    assert result['intent'] == intent
    assert result['verification']['status'] == 'NOT_RUN'
    assert result['evidence'] == {} and result['tool_calls'] == []
    assert '未呼叫' not in result['answer']
    model.assert_not_called()


def job(district, postings, workers, **changes):
    data = dict(available=True, district=district, snapshot_date='2026-10-05',
                industry_id='', retrieval_terms=['機械'], vacancy_postings=postings,
                requested_workers=workers, limit_reached_districts=[])
    return dict(tool='get_regional_job_demand', data={**data, **changes}, evidence={})


def test_opposite_rankings_are_explained_separately():
    answer = vacancy_comparison([job('西屯區', 35, 162), job('大雅區', 25, 245)])
    assert '刊登筆數：西屯區最多' in answer
    assert '需求人數：大雅區最多' in answer
    assert '35 筆' in answer and '245 人' in answer
    assert '機械' in answer and '不是實際缺工' in answer


@pytest.mark.parametrize('changes', [dict(snapshot_date='2026-10-04'), dict(retrieval_terms=['軟體']), dict(industry_id='IND_ICT')])
def test_incompatible_comparisons_do_not_rank(changes):
    answer = vacancy_comparison([job('西屯區', 35, 162), job('大雅區', 25, 245, **changes)])
    assert '不能直接比較' in answer and '最多' not in answer


def test_no_data_is_not_zero_and_capped_counts_are_samples():
    assert '不代表職缺為零' in vacancy_comparison([job('西屯區', 35, 162), job('大雅區', 0, 0, available=False)])
    assert '可觀測樣本' in vacancy_comparison([job('西屯區', 35, 162), job('大雅區', 25, 245, limit_reached_districts=['大雅區'])])


def test_taichung_districts_and_company_lookup_are_not_blocked():
    assert not unsupported_geography('台中市大雅區職缺')
    assert not unsupported_geography('查核台北機械公司統編')


def test_comparison_pipeline_replaces_ambiguous_model_answer():
    calls = [dict(id=str(i), function=dict(name='get_regional_job_demand', arguments=json.dumps(
        dict(district=d, industry_id='', occupation_keyword='機械')))) for i, d in enumerate(['西屯區', '大雅區'])]
    replies = [{'choices': [{'message': dict(tool_calls=calls)}]},
               {'choices': [{'message': dict(content='西屯比較多，可以招到999人。')}]}]
    with patch('agent.llm_agent._post_chat', side_effect=replies), patch('agent.llm_agent._run_tool', side_effect=[
        job('西屯區', 35, 162), job('大雅區', 25, 245)
    ]):
        result = OpenRouterAgent().process_query('西屯區和大雅區比，哪邊機械職缺多？')
    assert result['status'] == 'SUCCESS'
    assert '刊登筆數：西屯區最多' in result['answer']
    assert '需求人數：大雅區最多' in result['answer']
    assert '999' not in result['answer']
    assert len(result['structured_data']['tool_results']) == 2


def test_empty_official_dataset_has_independent_no_data_exit():
    call = dict(id='empty', function=dict(name='get_regional_job_demand', arguments=json.dumps(
        dict(district='大雅區', industry_id='', occupation_keyword=''))))
    replies = [{'choices': [{'message': dict(tool_calls=[call])}]},
               {'choices': [{'message': dict(content='缺工999人。')}]}]
    with patch('agent.llm_agent._post_chat', side_effect=replies), patch('agent.llm_agent._run_tool', return_value=dict(
        tool='get_regional_job_demand', data={'available': False, 'reason': '未匯入快照'}, evidence={}
    )):
        result = OpenRouterAgent().process_query('大雅區職缺')
    assert result['status'] == 'NO_DATA'
    assert result['verification']['status'] == 'NOT_RUN'
    assert '999' not in result['answer']


def test_model_cannot_replace_requested_district():
    call = dict(id='wrong', function=dict(name='get_regional_job_demand', arguments=json.dumps(
        dict(district='中區', industry_id='', occupation_keyword=''))))
    with patch('agent.llm_agent._post_chat', return_value={'choices': [{'message': dict(tool_calls=[call])}]}), \
         patch('agent.llm_agent.execute_tool') as tool:
        result = OpenRouterAgent().process_query('大雅區有多少職缺？')
    assert result['status'] == 'REJECTED'
    assert result['governance']['scope_guard']['category'] == 'GEOGRAPHY_MISMATCH'
    assert '不會以其他區' in result['answer']
    tool.assert_not_called()
