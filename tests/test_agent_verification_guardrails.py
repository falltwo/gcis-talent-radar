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

    def test_wage_answer_figures_are_copied_verbatim(self):
        data = {"data_period": "11412", "insured_units": 20056, "insured_people": 361509,
                "average_insured_salary": 36201.78}
        for answer, expected in (
            # 照抄工具數字；取整只限緊接在薪資標籤後的金額；期別代碼要寫在期別位置
            ("平均投保薪資為 36,201.78 元，投保人數 361,509 人，投保單位 20,056 家。", "VERIFIED"),
            ("資料期間 11412，平均投保薪資 36,201.78 元。", "VERIFIED"),
            ("資料期間為 114 年 12 月（11412）。", "VERIFIED"),
            ("平均投保薪資約 36,202 元。", "VERIFIED"),
            ("製造業平均月投保薪資為 36,202 元。", "VERIFIED"),
            ("平均投保薪資（非實領薪資）為 36,202 元。", "VERIFIED"),
            # 模型自行換算或約略的寫法不再放行：檢查器分不出它來自哪個欄位
            ("平均投保薪資約 3.6 萬元。", "FAILED"),
            ("平均投保薪資大約是36,200元。", "FAILED"),
            ("投保人數約 36.2 萬人。", "FAILED"),
            ("投保單位約 2.0 萬家。", "FAILED"),
            ("平均投保薪資約3.60萬元。", "FAILED"),
            ("平均投保薪資約36,200.00元。", "FAILED"),
            ("平均投保薪資 36,201 元。", "FAILED"),
            ("資料期間 11501。", "FAILED"),
            # 取整不能跨欄位、跨單位，期別代碼不能冒充數量
            ("工廠總數為36,202家。", "FAILED"),
            ("失業率為36,202%。", "FAILED"),
            ("資本額為 36,202 元。", "FAILED"),
            ("投保單位數為11412。", "FAILED"),
            # 期別說明寫在數字後面也算；「每月」「代碼」不是期別語境
            ("不可以。**11412 是資料期別**，表示民國114年12月，不是人數或單位數。", "VERIFIED"),
            ("11412（民國114年12月）的投保人數 361,509 人。", "VERIFIED"),
            ("資料期別：11412。", "VERIFIED"),
            ("投保人數每月為11412。", "FAILED"),
            ("投保單位數本月為11412。", "FAILED"),
            ("製造業行業代碼11412。", "FAILED"),
            ("投保人數為11412，是資料期別。", "FAILED"),
            ("投保人數為 11412（民國114年12月）。", "FAILED"),
            ("平均投保薪資（含加班費約）36,202 元。", "FAILED"),
            # 數字後附年月不能讓數量欄位的數字變成期別；只有數字自己開頭的句子才看後面
            ("投保人數 11412（民國114年12月）。", "FAILED"),
            ("投保單位 11412（民國114年12月）。", "FAILED"),
            ("投保人數達到11412（民國114年12月）。", "FAILED"),
            ("投保單位數等於11412（民國114年12月）。", "FAILED"),
            ("「11412」是資料期別。", "VERIFIED"),
            # 換行、逗號、冒號後面的數字仍屬於前面的欄位
            ("投保人數：\n11412（民國114年12月）。", "FAILED"),
            ("投保人數，11412 是資料期別。", "FAILED"),
            ("投保單位數：\n- 11412（民國114年12月）", "FAILED"),
            ("| 投保人數 | 11412（民國114年12月） |", "FAILED"),
            ("資料期別：\n11412。", "VERIFIED"),
            ("說明如下。\n\n11412 是資料期別，不是人數。", "VERIFIED"),
            # 期別說明前面只能是中性詞；欄位名接冒號、換行都像「欄位：值」
            ("投保人數：11412 是資料期別。", "FAILED"),
            ("投保人數\n11412 是資料期別。", "FAILED"),
            ("投保人數：11412 為資料期間內人數。", "FAILED"),
            ("投保人數不要把11412當成期別。", "FAILED"),
            ("答案：不可以，11412 是資料期別。", "VERIFIED"),
            ("不行：11412 是資料期別，表示民國114年12月。", "VERIFIED"),
            ("- 11412 是資料期別。", "VERIFIED"),
            ("### 結論\n11412 是資料期別。", "VERIFIED"),
            ("資料期別（11412）代表民國114年12月。", "VERIFIED"),
            ("資料期別：**11412**。", "VERIFIED"),
            ("11412 只是資料期別代碼。", "VERIFIED"),
            ("不應把 11412 當成數量，11412 是資料期別。", "VERIFIED"),
            ("11412（民國114年12月）的投保人數 361,509 人。", "VERIFIED"),
            # 中文數量對不到工具欄位，一律擋下；一般用語不受影響
            ("依勞動部統計缺工兩萬人。", "FAILED"),
            ("投保人數約三十六萬人。", "FAILED"),
            ("平均投保薪資約三萬六千元。", "FAILED"),
            ("比去年多兩成。", "FAILED"),
            ("超過一半的勞工投保。", "FAILED"),
            ("投保人數翻倍。", "FAILED"),
            ("前三名都一樣，最近一個月每一家企業都可以一起考慮，平均投保薪資 36,201.78 元。", "VERIFIED"),
        ):
            with self.subTest(answer=answer):
                self.assertEqual(verify_explanation_numbers(answer, data)["status"], expected)


    def test_small_values_must_match_exactly(self):
        # 原本固定 ±0.05 的容差，對 0.14 這種比值等於放行 30% 的誤差
        data = {"supply_demand_ratio": 0.14, "growth_rate": 3.2}
        for answer, expected in (
            ("每位畢業生對應 0.14 個職缺。", "VERIFIED"),
            ("成長率 3.2%。", "VERIFIED"),
            ("每位畢業生對應 0.18 個職缺。", "FAILED"),
            ("每位畢業生對應 0.10 個職缺。", "FAILED"),
            ("成長率 3.25%。", "FAILED"),
        ):
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

    def test_agent_wage_answer_must_copy_figures(self):
        wage = {"available": True, "data_period": "11412", "insured_units": 20056,
                "insured_people": 361509, "average_insured_salary": 36201.78}
        for content, expected in (
            ("平均投保薪資為 36,201.78 元，資料期間 11412。", "SUCCESS"),
            ("平均投保薪資約 3.6 萬元。", "FAILED"),
            ("工廠總數為36,202家。", "FAILED"),
            ("投保單位數為11412。", "FAILED"),
            ("投保人數每月為11412。", "FAILED"),
            ("投保人數 11412（民國114年12月）。", "FAILED"),
            ("投保單位數等於11412（民國114年12月）。", "FAILED"),
            ("投保人數：\n11412（民國114年12月）。", "FAILED"),
            # 真模型回答（組員實測 #8）：期別說明在數字後面，不能誤擋
            ("不可以。**11412 是資料期別**，表示民國114年12月，不是人數或單位數。\n\n"
             "查得的臺中市製造業資料中，該期的**投保人數為 361,509 人**，**投保單位數為 20,056 個**。"
             "這是勞保行業大類「製造業」的年末資料，不應把期別 11412 誤讀為數量。", "SUCCESS"),
        ):
            with self.subTest(content=content), (
                patch("agent.llm_agent._post_chat", side_effect=[
                    {"choices": [{"message": {"tool_calls": [{
                        "id": "call-1",
                        "function": {"name": "get_wage_baseline", "arguments": "{}"},
                    }]}}]},
                    {"choices": [{"message": {"content": content}}]},
                ])
            ), patch("agent.llm_agent._run_tool",
                     return_value={"tool": "get_wage_baseline", "data": wage, "evidence": {}}):
                response = OpenRouterAgent().process_query("台中製造業的平均投保薪資是多少？")
            self.assertEqual(response["status"], expected)
            self.assertEqual(content in response["answer"], expected == "SUCCESS")


if __name__ == "__main__":
    unittest.main()
