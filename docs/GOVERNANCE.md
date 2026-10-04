# 本地治理規則與稽核（PR #6）

## 執行順序

1. `HiringPatternGuard` 先檢查是否明確要求依年齡、性別等受保護特徵做招募決策。規則拒絕時直接回傳 `FAIR_HIRING_POLICY`，不呼叫任何模型。
2. `KeywordScopeGuard` 檢查問題是否屬於產品範圍。超出範圍時直接拒絕。
3. 僅當兩個規則均放行，且 `hiring_context` 為 true，並符合「`matched_traits` 非空或 `active_hiring_context` 為 true」時，才呼叫 `agent.policy_guard` 的第二關。這讓招募決策語境中的新說法即使沒有被第一關辨識為特徵，也會送交第二關；純年齡分布等沒有招募情境的統計問題不觸發。一般職缺查詢（例如大雅區職缺數）不呼叫 safeguard。此調整會增加招募情境問題的第二關呼叫量，單次呼叫仍受 5 秒逾時限制。
4. safeguard 回傳 `violation=true` 時以 `FAIR_HIRING_POLICY` 拒絕；`false` 時繼續。逾時、HTTP／網路錯誤、缺少金鑰或格式錯誤均 fail-open，沿用本地規則的放行結果。若稽核檔無法寫入，仍依既有治理規則停止請求。
5. 主回答模型收到放行問題後選擇唯讀工具。未查工具，或回答數字不受資料支持時，會被證據／數字閘門攔下。
6. 回傳前寫入結果稽核事件；事件保留 safeguard 是否呼叫、狀態、判斷、特徵類別及耗時，不保存 safeguard rationale、原始問題或模型推理過程。

`HiringPatternGuard` 與 `KeywordScopeGuard` 是本地規則，不是 AI 模型，亦沒有 TypeSafe API、經校準的置信度或 prompt injection 偵測模型。第二關預設使用 OpenRouter 模型 `openai/gpt-oss-safeguard-20b`，可用 `GUARD_MODEL` 調整；共用 `OPENROUTER_API_KEY`。沒有金鑰時只用本地規則。第二關採 5 秒逾時、low reasoning 及 JSON Schema 輸出；rationale 不會傳回 API 回應或稽核檔。

此模型的中文招募政策分類能力以 2026-10-05 的 32 題公開平衡題組初測：16 題應拒絕、16 題應放行。首輪 27 題成功產生可解析結果，27 題符合預期；5 題遇到 OpenRouter 上游 JSON 生成錯誤。重試後，29 題曾取得有效回應且都符合預期；D05、D09、D16 仍反覆失敗。首輪平均延遲 680.4 ms，首輪加一次重試的回報費用為 US$0.00324645。此樣本很小，不能宣稱一般準確率；錯誤時 fail-open 也表示第二關不可用時僅剩本地規則保護。測試案例與細節見 `scripts/eval_policy_guard.py`，仍須用未公開案例持續抽測。

2026-10-05 整合冒煙測試：真實 safeguard 對「台中製造業女性員工比例」回傳 `ALLOW`，耗時 930.8 ms；一般查詢「大雅區機械相關職缺有多少？」成功選到 `get_regional_job_demand`，且 safeguard 為 `NOT_CALLED_NOT_ELIGIBLE`。這次主回答的數字驗證回傳 `FAILED`，因此回答仍被既有數字閘門攔下；本次未修改 `numeric_verifier.py`。

產品範圍放行不等同有足夠資料回答，更不等同法律合規認證。規則和模型都可能誤判或漏判；評估案例不涵蓋所有中文表達，需持續人工檢查與加入回歸案例。

## 欄位契約

| 舊版 | 新版 |
| --- | --- |
| `agent.jev_model.JevDecisionModel` | `agent.keyword_scope_guard.KeywordScopeGuard` |
| `jev_model` | `keyword_scope_guard` |
| `governance.jev` | `governance.scope_guard` |
| scope `model` | `implementation: KeywordScopeGuard` 與 `version: keyword-scope-v2` |
| `confidence` | 移除；`rule_score` 僅表示命中關鍵字的加權分數 |
| audit `jev` | `scope_guard`；PR #6 使用 `schema_version: 2`，第二關事件使用 `schema_version: 3` |
| `JEV_SCOPE_REJECTED` | `KEYWORD_SCOPE_REJECTED` |

不提供舊 import／回應別名。既有稽核檔不改寫；下游讀取者須辨識沒有 schema_version 的舊事件，不能把舊 confidence 當模型機率。頂層 `model` 與日誌 `configured_model` 仍是回答模型的設定。

日誌保留 SHA-256、字元數、規則結果、工具名稱、核驗狀態與事件 ID，不保存問題原文、模型回答、工具原始資料、金鑰或 safeguard rationale。schema v3 新增 `policy_guard` 欄位，僅記 `called`、`status`、`decision`、`category`、`latency_ms`。放行前與結束時是不同事件 ID；回應的 `audit_id` 指向結果事件。SHA-256 不是匿名化保證，相同問題可被關聯；日誌仍應限制存取。

## 驗收

```bash
pip install fastapi uvicorn pandas numpy requests pytest statsmodels
python -m pytest tests -q
```

- `tests/test_governance_acceptance.py` 的 `REQUIRED`：驗收文件原有 17 題。
- `tests/test_policy_guard.py`：測試 safeguard 結構化輸出、違規／不違規、錯誤 fail-open、缺少金鑰略過、觸發條件及不記錄原文／rationale。
- `EXTRA`：原有額外 10 題。
- `VARIANTS`：官方資料、核心產品、英文／中文年齡、全形數字、統計、公平招募與混合意圖變體。
- `SECOND_REVIEW`：第二次驗收新增的 N01–N20；`SEMANTIC_VARIANTS`：統計與招募混合、否定作用範圍、相鄰指代及能力篩選變體。
- `THIRD_REVIEW`：逗號切段後延續徵才情境、純統計放行，以及工廠相關範圍詞，共 6 題。
- 每題都測規則本身與 mock 模型完整入口：拒絕題不得呼叫模型；放行題可進入模型，無工具證據的內容仍不得直接顯示。
- 另測空問題、無關問題、稽核不可寫、模型失敗與欄位遷移。
- 既有 `test_governance_guards.py` 僅更新改名後的欄位及原因碼，保留原斷言強度；main 原有測試不修改。

實際重新驗收結果、PR head 與 main SHA 記於 PR 說明。只有驗收者確認通過後才合併。區域同業工具與 PR #2 不在本次修改範圍。
