# 招募 Agent 後端（第一版）

依公司需求 → Agent 整理＋HR 核准 → 刊登／授權履歷匯入 → 人才比對 → 邀請 → 回覆 → 面試／錄用 → 看板的流程實作。這次只新增後端 API，沒有招募前端頁面。

## 執行與權限

沿用 `python server.py`、FastAPI 及 `database/mismatch_system.db`。第一次通過驗證的招募 API 呼叫會執行 `database/recruitment.sql` 的 additive migration，新增六張 `recruitment_*` 表，不變更官方資料表。部署前先備份資料庫；舊版程式可忽略新增的表，不需刪表回滾。

在私有 `.env` 設定 `RECRUITMENT_API_TOKENS_JSON`。未設定或格式錯誤時，招募 API 回傳 503；其他原有功能不受影響。

格式（下列是示意，請自行產生至少 32 字元的隨機 token）：

```text
RECRUITMENT_API_TOKENS_JSON={"<hr-random-token>":{"tenant_id":"company-a","actor_id":"hr-1","role":"hr"},"<recruiter-random-token>":{"tenant_id":"company-a","actor_id":"staff-1","role":"recruiter"}}
```

呼叫時使用 `Authorization: Bearer <token>`。tenant、actor 與 role 只由伺服器設定取得，呼叫者不能透過 body/header 自行指定企業。不同企業的資料與查詢均隔離；不存在或其他企業的物件回傳 404。

- `recruiter`：需求整理、草稿編修、授權履歷匯入、比對、邀請草稿、回覆登記與查詢。
- `hr`：包含上述權限，另可核准、登記刊登、登記發送／重試、補正履歷、改面試階段、關閉需求、停止聯絡及刪除資料。

這是後端服務憑證機制，不是終端使用者登入系統。正式多人產品仍需串接企業身分驗證、憑證輪替與 HTTPS。不要將這些服務 token 寫入前端、網址、儲存庫或記錄檔。

## API 操作順序

所有路徑以 `/api/recruitment` 開頭，亦可從 FastAPI `/docs` 的 Recruitment 區段查看 request schema。

| 步驟 | 方法與路徑 | 行為 |
|---|---|---|
| Agent 整理（可選） | `POST /requirements/prepare` | `{"needs":"大雅區招募CNC操作員…"}` → 回傳結構化欄位、缺漏欄位與待 HR 檢查提示 |
| 建立需求 | `POST /requests` | 建立 DRAFT，回傳 `id` 與 `revision` |
| 編修草稿 | `PUT /requests/{id}` | 完整取代草稿條件，revision 加一；核准後不可改，變更條件需另建需求 |
| HR 核准 | `POST /requests/{id}/approve` | 傳入 `{"expected_revision":1}`；版本不符回傳 409。DRAFT → APPROVED，保存核准人、時間與條件版本 |
| 登記刊登 | `POST /requests/{id}/publications` | 登記已在平台手動刊登的 `platform` 與 `external_id` |
| 匯入人選 | `POST /requests/{id}/candidates` | 匯入有權使用的結構化履歷，回傳 application ID 及 candidate ID |
| 補正履歷 | `PUT /candidates/{id}/evidence` | HR 補正結構化資料；清除既有比對，須重新比對 |
| 人才比對 | `POST /applications/{id}/match` | 回傳 MATCHED／NOT_MATCHED／NEEDS_REVIEW、逐項依據與需求版本 |
| 邀請草稿 | `POST /applications/{id}/invitations` | `{"message":"邀請訊息"}` → PENDING_APPROVAL |
| HR 核准邀請 | `POST /invitations/{id}/approve` | → APPROVED；有未知條件時必須明確傳 `{"reviewed_unknowns":true}` |
| 登記發送 | `POST /invitations/{id}/manual-delivery` | `{"outcome":"SENT","reference":"平台訊息編號或人工作業憑證"}`；失敗改用 FAILED |
| 重試核准 | `POST /invitations/{id}/retry` | 只允許 FAILED → APPROVED；最多登記三次發送嘗試 |
| 登記回覆 | `POST /invitations/{id}/manual-reply` | `{"outcome":"INTERESTED"}`；亦可 DECLINED、NO_RESPONSE |
| 面試／錄用 | `POST /applications/{id}/stage` | `{"stage":"INTERVIEW"}` → OFFERED → HIRED；亦可 REJECTED、WITHDRAWN |
| 關閉招募 | `POST /requests/{id}/close` | 關閉需求與已登記的刊登，取消尚在處理的邀請 |
| 停止聯絡 | `POST /candidates/{id}/opt-out` | 企業內該人選所有需求均停止聯絡 |
| 刪除人選 | `DELETE /candidates/{id}` | 級聯刪除履歷、應徵、比對及邀請訊息，保留無履歷內容的操作事件 |
| 到期清理 | `POST /retention/purge` | HR 清除所屬企業到期履歷及其關聯資料 |

查詢：`GET /requests`、`/applications`、`/publications`、`/invitations`、`/events`，支援 `limit`（1–200）、`offset`；applications/publications/invitations 可加 `request_id`。`GET /candidates/{id}` 讀取單一人選；`GET /dashboard` 彙整需求、應徵與邀請的各狀態筆數；`GET /platforms` 明確標示人工模式與未建置的平台自動化能力。

## 最小資料範例

建立需求（薪資統一為月薪新臺幣；投保薪資統計不會拿來自動補值）：

```json
{
  "title": "CNC操作員",
  "district": "大雅區",
  "shift": "日班",
  "headcount": 3,
  "required_skills": ["CNC"],
  "trainable_skills": ["機械製圖"],
  "min_experience_months": 12,
  "salary_min": 35000,
  "salary_max": 45000
}
```

匯入履歷（日期請換成未來日期，最長 366 天並附時區；以下資料僅為 schema 示意）：

```json
{
  "source": "104",
  "external_ref": "enterprise-authorized-candidate-001",
  "origin": "APPLIED",
  "display_name": "候選人代稱",
  "skills": ["CNC"],
  "available_shifts": ["日班"],
  "districts": ["大雅區"],
  "experience_months": 24,
  "rights_confirmed": true,
  "rights_basis": "企業確認有權匯入本次招募使用的資料",
  "expires_at": "2026-12-01T00:00:00+08:00"
}
```

`source` 可為 104／1111／direct／internal，`origin` 可為 APPLIED（主動應徵）或 SOURCED（授權來源）。相同企業＋source＋external_ref 的重複匯入，不會重建人選；同需求＋人選也不會重建應徵。資料不同時回傳 409，須由 HR 透過補正 API 處理。跨平台是否同一人需 HR 判斷，本版不會自動合併不同平台的人。

## Agent 與比對的界線

Agent prepare 端點需要既有 `OPENROUTER_API_KEY`，沿用 `OPENROUTER_MODEL`／`OPENROUTER_BASE_URL`。它只送出公司需求文字，不送履歷。回傳內容經 schema 檢查，但模型語意仍可能錯誤，因此每次標示 `requires_hr_review=true`，不自動建立或核准需求。未提及的欄位留空，HR 補齊後再提交結構化需求。沒有金鑰時仍可直接建立結構化需求，走完其餘流程。

比對不呼叫模型，依標準化後的精確技能、地區、班別與經驗月數產生逐項結果。可培訓技能不是淘汰條件。缺漏值 `null` 是 UNKNOWN，明確空清單是已知不符合；已知必要條件不符優先回傳 NOT_MATCHED。結果不代表錄取機率或履歷真實性。沒有同義詞推論，HR 應先統一詞彙。

需求與候選人欄位使用 allowlist，額外的年齡、性別等欄位回傳 422；需求文字另套用既有保護特徵規則，不能視為完整法律或語意合規保證。候選人結構化資料應由企業依有權使用的履歷正確整理，不提供公開搜尋人才庫。

## 狀態與資料一致性

- 未核准需求不能匯入人才或登記刊登。需求核准後凍結條件，避免舊 HR 核准套到新條件。
- 已知不符合必要條件不能建立邀請；資料不足由 HR 明確認可未知項目，或先補正再比對。
- 建立邀請後凍結比對與人選證據，避免已核准訊息依據被靜默改寫。
- 每筆應徵最多一份邀請，SENT 不可再次發送。相同狀態與 reference 的重複發送登記是冪等操作，並行重試也只記一次。
- 發送失敗只能經 HR 重試；參考編號應使用穩定、不含個資的作業憑證。邀請表保存最近一次憑證、累計嘗試數，事件表保存狀態操作歷程。
- 拒絕、未回覆結案、撤回、拒絕錄用、停止聯絡或職缺關閉，均阻止後續邀請。未回覆由 HR 限次人工追蹤後結案，本版不提供自動排程提醒。
- 面試流程只允許 INTERESTED → INTERVIEW → OFFERED → HIRED，不能直接跳到錄用。
- 寫入使用 SQLite transaction，核准／狀態檢查與資料更新一併提交；操作事件寫入失敗會回滾，不留下半完成狀態。
- events 只記企業、操作者、物件 ID、動作與時間，不複製履歷或邀請內容。

## 平台介接與資料保管

目前不呼叫 104／1111、不抓取平台履歷，也不自動發訊息。`manual-delivery` 是 HR 登記已完成的發送結果，不表示本服務已向平台發送；關閉或取消也只更新本地狀態，HR 仍需在平台端關閉職缺或停止作業。

104 官方公開的企業職缺同步／履歷傳輸服務，可在後續取得權限與技術契約後實作 adapter。人才搜尋、邀請發送及回覆同步必須各自確認；1111 另行確認。參考：https://ats.104.com.tw/job-resume-api 。

SQLite 檔內存有履歷欄位與邀請內容，依賴部署環境保護檔案與備份；本版未加入資料庫加密。到期後讀取人選回傳 410，應徵與邀請列表不再回傳到期資料，也不能進行邀請。操作人員應定期執行 purge（例如每日），才能移除實體資料；dashboard 是資料庫各狀態的彙總，可能包含尚未清理的到期案件。

正式多企業部署前應補齊企業登入、權限管理、備份／復原、保存政策與監控。SQLite 適合目前單機試作；高併發時再遷移至 PostgreSQL。此 PR 不包含前端看板、面試行事曆或實際寄信服務。

## 驗證

```bash
python -m pip install pytest pandas numpy requests xlrd openpyxl statsmodels fastapi uvicorn httpx
python -X utf8 -m pytest tests -q
```

`tests/test_recruitment.py` 使用隔離 SQLite 與 ASGI 呼叫；模型介接全部 mock，不會聯絡真人或消耗 API 額度。涵蓋流程、租戶／角色權限、缺漏條件、人工回覆、並行重複登記、重試上限、停止條件、保存到期與刪除、稽核失敗回滾、Agent 失敗及資料補正。
