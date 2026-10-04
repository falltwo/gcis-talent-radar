import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agent.audit_log import AuditLogError
from agent.llm_agent import OpenRouterAgent
from agent.prompt_guard import inspect_hiring_prompt


class HiringPromptGuardTests(unittest.TestCase):
    def test_blocks_selection_by_age_and_gender(self):
        result = inspect_hiring_prompt("製造業招募時只錄取 35 歲以下男性嗎？")

        self.assertEqual(result["decision"], "REJECT")
        self.assertIn("年齡", result["matched_traits"])
        self.assertIn("性別／性別認同", result["matched_traits"])

    def test_allows_fair_hiring_guidance(self):
        result = inspect_hiring_prompt("如何避免招募中的性別歧視？")

        self.assertEqual(result["decision"], "ALLOW")
        self.assertTrue(result["fair_hiring_education"])

    def test_fairness_wording_does_not_override_a_discriminatory_action(self):
        result = inspect_hiring_prompt("如何避免招募中的性別歧視？只錄取男性可以嗎？")

        self.assertEqual(result["decision"], "REJECT")
        self.assertTrue(result["discriminatory_decision_request"])


class GovernancePipelineTests(unittest.TestCase):
    def test_policy_rejection_happens_before_model_and_is_audited_without_raw_prompt(self):
        query = "我們公司只招年輕男性員工"
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = os.path.join(temp_dir, "audit.jsonl")
            with patch.dict(os.environ, {"AGENT_AUDIT_LOG_PATH": log_path}), patch(
                "agent.llm_agent._post_chat"
            ) as model_call:
                response = OpenRouterAgent().process_query(query)

            model_call.assert_not_called()
            self.assertEqual(response["status"], "REJECTED")
            self.assertEqual(response["intent"], "FAIR_HIRING_POLICY")
            self.assertIn("不協助依性別", response["answer"])
            self.assertTrue(response["governance"]["audit_id"])

            with open(log_path, encoding="utf-8") as stream:
                event = json.loads(stream.readline())
            self.assertEqual(event["outcome"], "FAIR_HIRING_POLICY_REJECTED")
            self.assertFalse(event["model_called"])
            self.assertIn("性別／性別認同", event["prompt_guard"]["matched_traits"])
            self.assertNotIn(query, json.dumps(event, ensure_ascii=False))
            self.assertEqual(len(event["query_sha256"]), 64)

    def test_keyword_scope_rejects_out_of_scope_before_model_and_logs_decision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = os.path.join(temp_dir, "audit.jsonl")
            with patch.dict(os.environ, {"AGENT_AUDIT_LOG_PATH": log_path}), patch(
                "agent.llm_agent._post_chat"
            ) as model_call:
                response = OpenRouterAgent().process_query("幫我寫一首情詩")

            model_call.assert_not_called()
            self.assertEqual(response["status"], "REJECTED")
            self.assertEqual(response["governance"]["scope_guard"]["decision"], "REJECT")
            with open(log_path, encoding="utf-8") as stream:
                event = json.loads(stream.readline())
            self.assertEqual(event["outcome"], "KEYWORD_SCOPE_REJECTED")
            self.assertFalse(event["model_called"])

    def test_policy_rejection_fails_closed_if_audit_log_cannot_be_written(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"AGENT_AUDIT_LOG_PATH": temp_dir}):
                with self.assertRaises(AuditLogError):
                    OpenRouterAgent().process_query("招募時只錄取女性")


if __name__ == "__main__":
    unittest.main()
