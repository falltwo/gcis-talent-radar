"""Exercise the LLM tool boundary with real local data and mocked model replies."""
import json
import os
import runpy
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent.agent_service import agent_service
from agent.llm_agent import OpenRouterAgent, OpenRouterError, ROUTES, TOOLS, _run_tool

CASES = [
    ("get_regional_job_demand", {"district": "大雅區", "industry_id": "IND_MFG", "occupation_keyword": ""}, "JOB_DEMAND_QUERY", "requested_workers"),
    ("get_gcis_new_company_trend", {"industry_id": "IND_MFG", "months": 6}, "COMPANY_TREND_QUERY", "latest_new_companies"),
    ("get_wage_baseline", {"industry_id": "IND_MFG"}, "WAGE_QUERY", "average_insured_salary"),
]


def model_call(name, args, call_id="official"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def model_reply(**message):
    return {"choices": [{"message": {"role": "assistant", **message}}]}


class OfficialLLMIntegrationTests(unittest.TestCase):
    def test_single_service_and_tool_schema_route_parity(self):
        self.assertIsInstance(agent_service, OpenRouterAgent)
        names = [t["function"]["name"] for t in TOOLS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(ROUTES))
        for name, _, intent, _ in CASES:
            self.assertEqual(ROUTES[name][0], intent)

    def test_each_official_tool_runs_through_model_loop_with_citations(self):
        for name, args, intent, metric in CASES:
            with self.subTest(tool=name):
                expected = _run_tool(name, json.dumps(args))
                self.assertTrue(expected["data"]["available"])
                narrative = f"工具觀測值為 {expected['data'][metric]}。"
                with patch("agent.llm_agent._post_chat", side_effect=[
                    model_reply(tool_calls=[model_call(name, args)]), model_reply(content=narrative)
                ]) as model:
                    result = agent_service.process_query("查詢官方資料")
                self.assertEqual(result["status"], "SUCCESS")
                self.assertEqual(result["intent"], intent)
                self.assertEqual(result["verification"]["status"], "VERIFIED")
                for url in expected["evidence"]["source_urls"]:
                    self.assertIn(url, result["answer"])
                self.assertEqual(result["evidence"]["quality_limitations"], expected["evidence"]["limitations"])
                sent = json.loads(model.call_args.args[0][-1]["content"])
                self.assertEqual(sent["limitations"], expected["evidence"]["limitations"])

    def test_multiple_official_tools_preserve_evidence(self):
        calls = [model_call(name, args, str(i)) for i, (name, args, _, _) in enumerate(CASES)]
        with patch("agent.llm_agent._post_chat", side_effect=[
            model_reply(tool_calls=calls), model_reply(content="已查得官方觀測資料，須依各資料的限制解讀。")
        ]):
            result = agent_service.process_query("綜合比較職缺、公司新設及投保薪資")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["intent"], "MULTI_TOOL_QUERY")
        self.assertEqual(len(result["evidence"]["tool_evidence"]), 3)
        self.assertEqual(len(result["evidence"]["dataset_ids"]), 3)
        self.assertTrue(result["evidence"]["quality_limitations"])

    def test_invalid_official_arguments_rejected_before_dispatch(self):
        bad = [
            ("get_gcis_new_company_trend", {"industry_id": "IND_MFG", "months": value})
            for value in [0, 181, True, "6"]
        ] + [
            ("get_wage_baseline", {"industry_id": "UNKNOWN"}),
            ("get_wage_baseline", {"industry_id": ""}),
            ("get_regional_job_demand", {"district": "台北市", "industry_id": "", "occupation_keyword": ""}),
            ("get_regional_job_demand", {"district": "", "industry_id": ""}),
        ]
        with patch("agent.llm_agent.execute_tool") as execute:
            for name, args in bad:
                with self.subTest(args=args), self.assertRaises(OpenRouterError):
                    _run_tool(name, json.dumps(args))
            execute.assert_not_called()

    def test_all_city_and_unfiltered_jobs_are_supported(self):
        result = _run_tool("get_regional_job_demand", json.dumps({
            "district": "", "industry_id": "", "occupation_keyword": ""
        }))
        self.assertTrue(result["data"]["available"])
        self.assertFalse(result["data"]["retrieval_terms"])
        self.assertGreater(result["data"]["vacancy_postings"], 0)

    def test_launcher_keeps_utf8_and_loads_env_before_uvicorn(self):
        launcher = Path(__file__).resolve().parents[1] / "server.py"
        with patch.dict(os.environ, {"OPENROUTER_MODEL": "existing-model"}, clear=True):
            def check_start(*args, **kwargs):
                self.assertEqual(os.environ["OPENROUTER_API_KEY"], "test-only-key")
                self.assertEqual(os.environ["OPENROUTER_MODEL"], "existing-model")
            with patch("sys.stdout", Mock()) as stdout, patch("sys.stderr", Mock()) as stderr, \
                 patch("socket.socket") as socket, patch("pathlib.Path.is_file", return_value=True), \
                 patch("pathlib.Path.read_text", return_value='OPENROUTER_API_KEY="test-only-key"\nOPENROUTER_MODEL=file-model\n'), \
                 patch("uvicorn.run", side_effect=check_start) as run:
                socket.return_value.__enter__.return_value.connect_ex.return_value = 1
                runpy.run_path(str(launcher), run_name="__main__")
                stdout.reconfigure.assert_called_with(encoding="utf-8")
                stderr.reconfigure.assert_called_with(encoding="utf-8")
                run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
