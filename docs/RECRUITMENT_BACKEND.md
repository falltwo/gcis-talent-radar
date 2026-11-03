# 招募 Agent 後端（第一版）

依公司需求 → Agent 整理＋HR 核准 → 刊登／授權履歷匯入 → 人才比對 → 邀請 → 回覆 → 面試／錄用 → 看板的流程實作。包含後端 API 及獨立的104模擬刊登展示頁；尚未提供正式企業招募前端。

## 執行與權限

沿用 `python server.py`、FastAPI 及 `database/mismatch_system.db`。第一次通過驗證的招募 API 呼叫會執行 `database/recruitment.sql` 的 additive migration，新增七張 `recruitment_*` 表（含獨立的模擬刊登表），不變更官方資料表。部署前先備份資料庫；舊版程式可忽略新增的表，不需刪表回滾。

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

## 104 模擬刊登

不需要實際公司、104 帳號、104 金鑰或 OpenRouter 金鑰。這是本系統自己的模擬器，**不是104提供的 sandbox**。模組不使用任何 HTTP client，不對外連線，也不會把模擬成功紀錄放進人工刊登表。

狀態流程：`PENDING_APPROVAL`（待核准）→ `PROCESSING`（處理中）→ `SUCCEEDED`（成功）或 `FAILED`（失敗）。關閉招募需求時，尚待核准、處理中或失敗待重試的模擬會改成 `CANCELLED`。

| 操作 | 路徑與輸入 | 顯示結果 |
|---|---|---|
| 建立模擬 | `POST /requests/{id}/simulated-publications`，`{"idempotency_key":"demo-001","scenario":"SUCCESS"}` | 模擬刊登：待核准 |
| HR 核准並啟動 | `POST /simulated-publications/{id}/approve` | 模擬刊登：處理中 |
| 完成本次模擬 | `POST /simulated-publications/{id}/complete` | SUCCESS 情境成功；FAILURE 情境失敗 |
| 失敗後申請重試 | `POST /simulated-publications/{id}/retry`，`{"scenario":"SUCCESS"}` | 回到待核准；HR 必須再次核准 |
| 查詢狀態 | `GET /simulated-publications/{id}` | 狀態、中文標籤、核准人、嘗試數、模擬編號或錯誤碼 |
| 列表 | `GET /simulated-publications?request_id={id}` | 分頁列表，明確標示模擬 |

需求本身須先經 HR 核准。recruiter 可建立模擬，但核准、完成與重試限 HR。沒有背景排程；`complete` 是手動推進模擬工作的一步，故處理中狀態能穩定留在畫面供展示，程序重啟後也能繼續。

建立時以 `scenario` 指定結果；只有 FAILURE 可重試，每筆最多三次執行。同 key 重複建立回傳原紀錄，不同 key 不允許為同一需求產生第二筆模擬；請用 retry。重複核准處理中紀錄、重複完成終態紀錄，都不增加嘗試數或重複寫事件。

所有模擬紀錄回應固定包含：

```json
{
  "platform": "104",
  "mode": "SIMULATION",
  "is_simulated": true,
  "sent_to_platform": false,
  "status": "SUCCEEDED",
  "status_label": "模擬刊登：成功",
  "notice": "僅為104刊登流程模擬，未送至104，未建立真實職缺。"
}
```

成功時只有 `sim104-...` 模擬編號，沒有真實104職缺網址。前端應持續顯示 `notice` 與 `status_label`，不可只顯示「已刊登到104」。看板另以 `simulated_publications` 欄位統計，不與真實人工刊登混合。

可直接執行離線展示，不必先設定服務憑證或啟動伺服器：

```bash
python -X utf8 -m recruitment.demo
```

這個指令使用獨立暫存 SQLite、虛構職缺及示範 HR，印出成功與失敗兩條流程。結束後刪除暫存資料庫，不修改正式資料庫。

### 網頁展示

啟動 `python server.py` 後，開啟 `/recruitment-demo`；首頁的「模擬招募」也可進入。畫面提供職缺預覽、狀態流程、示範 HR 核准、取得結果、重試與操作紀錄，支援桌面及手機。

頁面使用 `/api/recruitment-demo/*`，不需要企業服務 token。所有招募需求都是伺服器產生的固定虛構資料，不接受企業 ID、正式需求 ID 或金鑰；沒有讀寫正式資料庫的入口。每個展示使用獨立暫存 SQLite，以隨機 HttpOnly／SameSite=strict cookie 識別，最多32個並行展示、20分鐘到期，下次存取時清理；程序重啟後需重建。重新建立會刪除該瀏覽器上一份展示資料。

展示 API：`POST /start`（`{"scenario":"SUCCESS"}` 或 FAILURE）、`GET /state`、`POST /approve`、`POST /complete`、`POST /retry`（指定下一次 scenario）。沒有有效展示時，state 回傳204；動作回傳404。不同來源的瀏覽器寫入會被拒絕。這是固定情境的展示工具，示範 HR 身分不可用於正式企業 API。

### 模擬求才網站 `/mock104`

「橙才招募管理」是一個參考求才平台操作方式的獨立模擬網站，使用自己的名稱與介面，清楚標示非104官方網站。首頁提供「模擬求才平台」入口。

可操作的流程：職缺管理 → 新增職缺 → 基本資訊 → 工作條件 → 儲存草稿／預覽 → 送出刊登申請 → 模擬平台核准 → 處理中 → 成功或失敗。失敗可申請重審，成功的職缺會出現在「求職者預覽」；關閉後從預覽移除。求職者頁面不接受履歷或應徵。

表單可填職稱、示範企業名稱、全職／兼職、地區、工作內容、月薪、班別、人數、經驗、必要與可培訓技能。「帶入示範內容」可快速試走流程；草稿可修改，送審後內容凍結。薪資範圍與必填欄位會驗證，工作內容至少10字才能送審。

API 使用獨立的 `/api/mock104/*` 及 HttpOnly／SameSite cookie；沿用暫存工作階段、來源檢查與模擬狀態機。每個瀏覽器最多50筆職缺，最多32個並行展示，20分鐘到期。工作內容等額外資料只存該展示資料庫的 `mock_job_details` 表，不新增正式資料庫表。不需企業 token、OpenRouter 或104金鑰，不呼叫任何正式平台介面。

- `POST /start`：建立或取回本瀏覽器的展示。
- `GET /state`：職缺與模擬狀態列表；重新整理後仍可讀取。
- `POST /jobs`、`PUT /jobs/{id}`：建立／編修草稿。
- `POST /jobs/{id}/submit`：送審，指定 `scenario` 為 SUCCESS 或 FAILURE。
- `POST /jobs/{id}/approve`、`/complete`：模擬核准、完成處理；網站核准後延遲約一秒自動推進本地結果。
- `POST /jobs/{id}/retry`：失敗後重新送審，仍須核准。
- `POST /jobs/{id}/close`：關閉模擬職缺。

`tests/test_mock104.py` 驗證草稿修改、重複送審、刊登／關閉、失敗重試、瀏覽器隔離、跨來源保護與禁止 LIVE／企業 ID 等欄位。網站桌面及手機版已以真實瀏覽器走過刊登與重試流程。

### 一般網站與外部 Computer Use

功能流程圖與例外處理：[招募功能流程](RECRUITMENT_FLOW.md)。另附[單頁圖解](recruitment-workflow.html)。

`/mock104` 是一般求才網頁。已移除頁內逐欄填表腳本、`window.MockPortal`、Agent 自訂DOM事件及Agent專用刊登旗標。手動使用或其他Computer Use工具均走相同的表單、預覽、送審流程；一般網站不會替Agent推進工作狀態。

選單使用一般網頁內的 combobox／listbox，避免Windows原生選單彈出時阻擋瀏覽器截圖。支援滑鼠點選、方向鍵、Home／End、Enter確認、Esc取消及Tab離開；原表單仍負責提交資料。每次截圖最多等待10秒。已儲存但與核准資料不同的欄位會回饋給模型，要求返回編輯修正，不能跳過核對。工作台僅保留「產生招募建議（範本／網路）」入口，依輸入職位自動選擇範本或網路研究。

`/recruitment-agent` 是獨立的需求整理與操作控制台：

工作台HTML與程式皆回傳`Cache-Control: no-store`。程式網址包含依檔案內容計算的版本碼；程式更新後網址隨之變更，避免內建瀏覽器把新版表單與舊版按鈕事件混用。過期版本網址回傳404，重新載入工作台可取得目前版本。

1. 輸入職位及簡短條件，例如「會計；招募三人，月薪面議」。公司名稱可以稍後確認，不會編造公司事實。
2. 常見職位使用具來源的職業範本。目前內建35類，完整職稱與別名見 [常見職缺範本清單](COMMON_JOB_TEMPLATES.md)。來源為O*NET，各模板的工作內容為自行整理的建議；UI明確標示不是本次即時抓取。中英文別名、空格及全形字會統一比對；未列入的專業或複合職稱仍搜尋，不以「工程師」等子字串任意套用。範本不呼叫模型或網路，不消耗搜尋次數；企劃助理先用一般企劃行政支援，行銷或活動方向交由HR確認。
3. 工作台先呼叫 `/api/mock104/agent/strategy?role=職稱`，顯示這次是本機範本或即時搜尋；範本請求最多等待15秒，搜尋請求最多等待60秒，逾時會取消前端等待、顯示錯誤並恢復按鈕。後端搜尋設定連線5秒、讀取45秒上限。重新產生建議時先隱藏舊的審核表，避免誤用先前內容。其他職位（例如量子研究師）透過OpenRouter web plugin即時搜尋（Exa），優先研究機構、政府、大學及雇主資料，回傳可點開的來源與查詢時間。沒有可追溯來源或搜尋失敗時回傳錯誤，不會偽裝為已搜尋。
4. 程式保留HR已明示的人數、面議／薪資區間、班制、時段與經驗；工作內容保留HR原文。補全的工作內容、技能、班制、時間等標成「建議／待確認」，不代表公司既定要求。冷門職位另列研究方向等待確認事項。
5. HR確認後，另開獨立Chrome；外部程序讀取截圖，由視覺模型決定滑鼠、鍵盤及捲動。不是網站自填動畫，也不使用DOM選擇器填表、頁面evaluate或隱藏API新增職缺。
6. 程序只允許本機模擬網站，使用獨立瀏覽器context及該展示的cookie，不使用使用者個人Chrome登入。攔截其他來源及Agent控制API的頁面請求，禁止任意網址輸入與未核准文字，最多30次畫面決策、最多2個並行瀏覽器。
7. 後端獨立觀察已儲存的職缺，只有與HR核准資料完全相符才認定填表完成。預設停在第二次HR確認；可在Chrome直接按一般網站的送出，或回控制台點確認繼續。也可在第一次核准時取消第二次確認，自動完成本地模擬刊登。
8. 可停止操作；目前模型回合返回後、下一個滑鼠鍵盤動作之前會檢查停止狀態。完成後Chrome保留最多5分鐘供檢視，也可自行關閉。

薪資使用 `salary_mode=NEGOTIABLE` 時，`salary_min`／`salary_max` 都是null，網站直接顯示「薪資面議」；不會填零或捏造區間。`RANGE` 才要求有效上下限。會計範本不會把HR的面議條件改成估計薪資。

本機安裝與設定：

```bash
python -m pip install -r requirements-recruitment-browser.txt
# 需已安裝 Google Chrome；Playwright 使用 channel=chrome，無需額外下載瀏覽器。
python server.py
```

`.env` 設定既有 `OPENROUTER_API_KEY`、`RECRUITMENT_AGENT_DEMO_AI_ENABLED=1`。可用 `RECRUITMENT_COMPUTER_MODEL` 指定支援圖片輸入與JSON輸出的模型，預設沿用 `OPENROUTER_MODEL`。常見職位的範本補全不需要金鑰；即時搜尋及Computer Use需要模型／網路，會使用帳戶額度。即時整理每session最多3次，全服務每分鐘最多10次。

研究來源、欄位來源（HR_INPUT／SUGGESTED）及確認事項會在表單中顯示。Company資訊只取自HR輸入；不把網路參考職缺的公司名稱、福利、薪資或學歷門檻硬套成自家公司規定。範本、搜尋及最後刊登內容都需HR核准。

測試：會計稀疏需求、明示條件優先、面議不含區間、量子研究網路來源、無引用拒絕、鍵鼠白名單、停止及本機限制。已用真實模型與獨立Chrome完成會計一般網頁填表、HR確認及模擬刊登；亦實測量子研究師即時搜尋回傳研究機構來源。沒有操作真實104。

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

正式多企業部署前應補齊企業登入、權限管理、備份／復原、保存政策與監控。SQLite 適合目前單機試作；高併發時再遷移至 PostgreSQL。此 PR 不包含正式企業前端看板、面試行事曆或實際寄信服務。

## 驗證

```bash
python -m pip install pytest pandas numpy requests xlrd openpyxl statsmodels fastapi uvicorn httpx
python -X utf8 -m pytest tests -q
```

`tests/test_recruitment.py` 使用隔離 SQLite 與 ASGI 呼叫；模型介接全部 mock，不會聯絡真人或消耗 API 額度。涵蓋流程、租戶／角色權限、缺漏條件、人工回覆、並行重複登記、重試上限、停止條件、保存到期與刪除、稽核失敗回滾、Agent 失敗及資料補正。
