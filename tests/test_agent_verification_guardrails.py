import unittest
from unittest.mock import patch

from agent.llm_agent import OpenRouterAgent
from agent.numeric_verifier import verify_explanation_numbers


class NumericVerifierGuardrailTests(unittest.TestCase):
    def test_empty_tool_data_cannot_verify_fabricated_numbers(self):
        result = verify_explanation_numbers(
            "未來 5 年缺工 2 萬人，預測達 117。",
            {},
        )

        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["accuracy_pct"], 0.0)

    def test_generic_constants_are_not_implicitly_accepted(self):
        result = verify_explanation_numbers(
            "台中有 29 個行政區，預測年為 117。",
            {"population": 1000},
        )

        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["matched_count"], 0)

    def test_no_numeric_claims_are_not_reported_as_verified(self):
        result = verify_explanation_numbers("目前工具資料顯示有變化。", {"count": 3})

        self.assertEqual(result["status"], "NOT_APPLICABLE")
        self.assertIsNone(result["accuracy_pct"])

    def test_any_unsupported_number_prevents_full_verification(self):
        result = verify_explanation_numbers(
            "1000、1000、1000、1000；另有 2。",
            {"count": 1000},
        )

        self.assertEqual(result["status"], "WARNING")
        self.assertEqual(result["accuracy_pct"], 80.0)

    def test_claimed_user_plan_is_not_verified_by_unrelated_tool_count(self):
        for query in (None, "台中有 10 人的職缺嗎？"):
            with self.subTest(query=query):
                result = verify_explanation_numbers(
                    "你預計招募10人。", {"vacancies": 10}, user_query=query,
                )
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["user_condition_count"], 0)
                self.assertEqual(result["matched_count"], 0)

    def test_request_for_information_is_not_a_personal_hiring_plan(self):
        for query in (
            "我想知道台中招募10人的職缺有幾筆？",
            "我們想知道台中招募10人的職缺有幾筆？",
            "我要找招募10人的職缺",
            "我們公司想查台中招募10人的職缺",
        ):
            with self.subTest(query=query):
                result = verify_explanation_numbers(
                    "你預計招募10人。", {"vacancies": 10}, user_query=query,
                )
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["user_condition_count"], 0)
    def test_changed_user_plan_is_rejected_even_if_tool_has_same_count(self):
        result = verify_explanation_numbers(
            "你預計招募20人。", {"vacancies": 20},
            user_query="我預計招募10人，請查台中職缺。",
        )
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["user_condition_count"], 0)
        self.assertEqual(result["matched_count"], 0)

    def test_metadata_rounding_and_no_number_regressions(self):
        examples = (
            ("資料日期為2025-08-01。", {"snapshot_date": "2025-08-01"}, "VERIFIED"),
            ("目前工具資料顯示有變化。", {"count": 3}, "NOT_APPLICABLE"),
            ("薪資約 3 萬元。", {"monthly_salary": 30000}, "VERIFIED"),
        )
        for answer, data, expected in examples:
            with self.subTest(answer=answer):
                self.assertEqual(verify_explanation_numbers(answer, data)["status"], expected)


class AgentResponseGuardrailTests(unittest.TestCase):
    def test_agent_hides_unverified_claim_about_user_plan(self):
        scenarios = (
            ("台中有 10 人的職缺嗎？", "你預計招募10人。", 10),
            ("我預計招募10人，請查台中職缺。", "你預計招募20人。", 20),
        )
        for query, narrative, tool_count in scenarios:
            with self.subTest(query=query):
                agent = OpenRouterAgent()
                with (
                    patch("agent.llm_agent._post_chat", side_effect=[
                        {"choices": [{"message": {"tool_calls": [{"id": "call-1", "function": {
                            "name": "get_regional_job_demand", "arguments": "{}",
                        }}]}}]},
                        {"choices": [{"message": {"content": narrative}}]},
                    ]),
                    patch("agent.llm_agent._run_tool", return_value={
                        "tool": "get_regional_job_demand", "data": {"vacancies": tool_count}, "evidence": {},
                    }),
                ):
                    response = agent.process_query(query)

                self.assertEqual(response["status"], "FAILED")
                self.assertEqual(response["verification"]["status"], "FAILED")
                self.assertNotIn(narrative, response["answer"])

    def test_agent_checks_a_stated_user_plan_against_the_original_query(self):
        agent = OpenRouterAgent()
        with (
            patch("agent.llm_agent._post_chat", side_effect=[
                {"choices": [{"message": {"tool_calls": [{"id": "call-1", "function": {
                    "name": "get_regional_job_demand", "arguments": "{}",
                }}]}}]},
                {"choices": [{"message": {"content": "你預計招募10人。"}}]},
            ]),
            patch("agent.llm_agent._run_tool", return_value={
                "tool": "get_regional_job_demand", "data": {"vacancies": 15}, "evidence": {},
            }),
        ):
            response = agent.process_query("我預計招募10人，請查台中職缺。")

        self.assertEqual(response["status"], "SUCCESS")
        self.assertEqual(response["verification"]["status"], "NOT_APPLICABLE")
        self.assertEqual(response["verification"]["user_condition_count"], 1)
        self.assertIn("你預計招募10人", response["answer"])

    def test_model_answer_without_tool_call_is_suppressed(self):
        agent = OpenRouterAgent()
        with patch(
            "agent.llm_agent._post_chat",
            return_value={"choices": [{"message": {"content": "依勞動部統計缺工 2 萬人。"}}]},
        ):
            response = agent.process_query("製造業缺工多少？")

        self.assertEqual(response["status"], "FAILED")
        self.assertEqual(response["tool_calls"], [])
        self.assertNotIn("依勞動部統計", response["answer"])

    def test_failed_numeric_audit_suppresses_model_answer(self):
        agent = OpenRouterAgent()
        with (
            patch(
                "agent.llm_agent._post_chat",
                side_effect=[
                    {
                        "choices": [{
                            "message": {
                                "tool_calls": [{
                                    "id": "call-1",
                                    "function": {
                                        "name": "get_demographic_projection",
                                        "arguments": "{}",
                                    },
                                }]
                            }
                        }]
                    },
                    {"choices": [{"message": {"content": "依勞動部統計缺工 2 萬人。"}}]},
                ],
            ),
            patch(
                "agent.llm_agent._run_tool",
                return_value={"tool": "get_demographic_projection", "data": {}, "evidence": {}},
            ),
        ):
            response = agent.process_query("製造業缺工多少？")

        self.assertEqual(response["status"], "FAILED")
        self.assertEqual(response["verification"]["status"], "FAILED")
        self.assertNotIn("依勞動部統計", response["answer"])


if __name__ == "__main__":
    unittest.main()
