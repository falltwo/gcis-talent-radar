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


class AgentResponseGuardrailTests(unittest.TestCase):
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
