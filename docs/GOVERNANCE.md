# 本地治理規則與稽核（PR #6）

## 執行順序

1. `KeywordScopeGuard` 用領域關鍵字與加權分數識別擴廠、人力、就業法規、官方資料等主題。
2. `HiringPatternGuard` 按語句片段檢查年齡、性別等特徵是否成為篩選、排除、錄用或排序條件；統計詞不會解除同句的選人限制。受否定或法規諮詢修飾的動作不視為要求執行；相鄰片段可辨識部分「她們／他們」指代。拒答優先於範圍判斷。
3. 任一前置規則拒絕時，記錄結果事件並回傳 `status: REJECTED`，不呼叫模型。
4. 放行後先記錄 `REQUEST_ACCEPTED`，再交給 OpenRouter 選擇唯讀工具。
5. 模型沒有使用工具，或回答數字不受資料支持，會被證據／數字閘門攔下。回答附官方工具的來源及資料限制。
6. 回傳前寫入結果稽核事件；寫入失敗則拋出 `AuditLogError`，API 回傳 503。

上述兩個治理元件均為本地規則，沒有治理模型、TypeSafe API、經校準的置信度或 prompt injection 偵測模型。產品範圍放行不等同有足夠資料回答，更不等同法律合規認證。指代處理僅限相鄰片段；隱喻、較長距離指代或新表達仍可能漏判，教育問句也可能誤擋。需持續人工檢查與加入回歸案例。

## 欄位契約

| 舊版 | 新版 |
| --- | --- |
| `agent.jev_model.JevDecisionModel` | `agent.keyword_scope_guard.KeywordScopeGuard` |
| `jev_model` | `keyword_scope_guard` |
| `governance.jev` | `governance.scope_guard` |
| scope `model` | `implementation: KeywordScopeGuard` 與 `version: keyword-scope-v2` |
| `confidence` | 移除；`rule_score` 僅表示命中關鍵字的加權分數 |
| audit `jev` | `scope_guard`，新事件 `schema_version: 2` |
| `JEV_SCOPE_REJECTED` | `KEYWORD_SCOPE_REJECTED` |

不提供舊 import／回應別名。既有稽核檔不改寫；下游讀取者須辨識沒有 schema_version 的舊事件，不能把舊 confidence 當模型機率。頂層 `model` 與日誌 `configured_model` 仍是回答模型的設定。

日誌保留 SHA-256、字元數、規則結果、工具名稱、核驗狀態與事件 ID，不保存問題原文、模型回答、工具原始資料或金鑰。放行前與結束時是不同事件 ID；回應的 `audit_id` 指向結果事件。SHA-256 不是匿名化保證，相同問題可被關聯；日誌仍應限制存取。

## 驗收

```bash
pip install fastapi uvicorn pandas numpy requests pytest statsmodels
python -m pytest tests -q
```

- `tests/test_governance_acceptance.py` 的 `REQUIRED`：驗收文件原有 17 題。
- `EXTRA`：原有額外 10 題。
- `VARIANTS`：官方資料、核心產品、英文／中文年齡、全形數字、統計、公平招募與混合意圖變體。
- `SECOND_REVIEW`：第二次驗收新增的 N01–N20；`SEMANTIC_VARIANTS`：統計與招募混合、否定作用範圍、相鄰指代及能力篩選變體。
- 每題都測規則本身與 mock 模型完整入口：拒絕題不得呼叫模型；放行題可進入模型，無工具證據的內容仍不得直接顯示。
- 另測空問題、無關問題、稽核不可寫、模型失敗與欄位遷移。
- 既有 `test_governance_guards.py` 僅更新改名後的欄位及原因碼，保留原斷言強度；main 原有測試不修改。

實際重新驗收結果、PR head 與 main SHA 記於 PR 說明。只有驗收者確認通過後才合併。區域同業工具與 PR #2 不在本次修改範圍。
