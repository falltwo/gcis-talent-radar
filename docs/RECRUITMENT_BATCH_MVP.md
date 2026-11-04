# 產業人才雷達：AI 招募後端整合

此模組與 PR22 原有的 `recruitment/` 流程並存；原有 `/api/recruitment/*`、`/recruitment-agent` 與 `/mock104` 保留。程式位於 `recruitment/backend/`，由既有 `api/main.py` 掛載於 `/api/recruitment/mvp`。與首頁使用同一服務埠；子服務的啟動／關閉生命週期由父服務執行。互動文件在 `/api/recruitment/mvp/docs`，JSON 規格在 `/api/recruitment/mvp/openapi.json`。主 `/docs` 不會展開掛載子服務的路由。

預設招募資料庫為專案的 `database/recruitment.sqlite3`，與產業分析資料庫分開。既有 `.env`、OpenRouter 金鑰與模型設定保留；使用該金鑰及模型時會有對應供應商費用。模型須支援 structured outputs，若既有 OPENROUTER_MODEL 不支援，請由管理者選擇合適模型；範例為 openai/gpt-4.1-mini。

**範圍：此整合提供後端。現有「刊登召募」前端仍是本機模擬，不會自動改成真實 API；job_postings 的正式刊登指寫入本系統資料庫，不代表發布至 104 或任何外站。** 未新增履歷蒐集或寄送功能。

# AI 智慧招募系統後端 MVP

可執行的 FastAPI + SQLAlchemy 2 + Pydantic 2 專案，預設 SQLite，支援 PostgreSQL。介面為 REST API，沒有前端。招募表是公司要找人的草稿／正式職缺，**不是求職者履歷**；本 MVP 不收集履歷、不實作 resumes / applications，也不以職缺資料冒充履歷。

## 設計依據與六階段

參考原對話可讀取的文字規則：需求解析 → 公司範本／薪資參考補齊 → 批次草稿 → HR 編輯 → HR 確認 → 交易式正式刊登。原對話工具回傳未包含網站截圖或最新流程圖附件，故尚未驗證畫面及圖中逐欄位對應。

1. HR 在聊天面板輸入需求，前端呼叫 `POST /batches`。
2. 有金鑰時透過 OpenRouter 擷取職稱、人數及 HR 已提供的文字欄位；後端核對原文薪資，依公司查詢範本補齊內容。缺金鑰或供應商失敗時使用規則解析。
3. 建立 recruitment_batches / recruitment_batch_items，回傳每項 missing_fields。
4. HR 以 PUT 編輯每項完整資料；範本／參考薪資須 confirm_salary=true。
5. `POST /batches/{id}/confirm` 檢查完整性。任一編輯會使整批回到 draft。
6. `POST /batches/{id}/publish` 一次建立全部 job_postings、更新狀態及操作紀錄，任何寫入失敗整批回滾。

薪資優先序：**HR 明確指定 > 同公司職缺範本 > 同公司薪資參考資料 > 留空追問**。解析及補齊不會覆蓋 HR 數值。只有 HR 編輯 API 能變更指定值；編輯紀錄保留前後值。範本和參考資料永遠是待確認建議。未內建任何市場薪資；新增參考資料必須提供 data_source，該欄為 HR 提供的來源文字，系統不宣稱已查證。薪資單位支援 monthly / hourly / yearly，幣別 MVP 僅 TWD。

## 本機啟動（PowerShell）

建議 Python 3.12–3.14；本次驗證使用 Python 3.14、SQLite。

```powershell
cd <產業人才雷達專案資料夾>
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -r requirements-recruitment.txt pandas numpy requests xlrd openpyxl statsmodels
# 已有 .env 請保留，依下方說明補上缺少的設定；不要覆蓋金鑰。
# 首次設定才執行 Copy-Item .env.example .env
.\.venv\Scripts\python server.py
```

開啟 [互動 API 文件](http://127.0.0.1:8888/api/recruitment/mvp/docs)。啟動時建立新資料庫的資料表。`.env` 以環境變數優先；啟動後以 server.py 輸出的網址為準，若自動換埠請同步修改 API 範例，請勿提交正式資料及密碼。

### PostgreSQL

先在 PostgreSQL 建立獨立的 recruitment 資料庫及帳號，再於 `.env` 設定連線字串：

```dotenv
RECRUITMENT_DATABASE_URL=postgresql+psycopg://recruitment:URL編碼後的密碼@localhost:5432/recruitment
```

再啟動 API。此模組未改動既有分析資料庫，不要將 RECRUITMENT_DATABASE_URL 指向 mismatch_system.db。現有資料表結構改版尚無 Alembic 遷移，正式資料庫變更需另建 migration；勿以刪除資料庫處理正式資料。

## API 完整使用範例（PowerShell）

```powershell
$base = 'http://127.0.0.1:8888/api/recruitment/mvp'
function Send-Json($method, $path, $body, $headers=@{}) {
  Invoke-RestMethod -Method $method -Uri "$base$path" -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 10)))
}
# 每次註冊建立新公司及該公司的 HR；不能自行指定既有 company_id 或 role。
Send-Json POST '/auth/register' @{company_name='示範公司';name='HR';email='hr@example.com';password='replace-with-a-long-password'}
$login = Send-Json POST '/auth/login' @{email='hr@example.com';password='replace-with-a-long-password'}
$headers = @{Authorization="Bearer $($login.access_token)"}

# 範本示例僅供測試，不是市場薪資。
foreach ($title in @('工程師','助理','除錯員','經理')) {
  Send-Json POST '/job-templates' @{title=$title;description='請依實際工作內容編輯';requirements='請依實際條件編輯';location='台北';salary_min=50000;salary_max=50000} $headers
}
Send-Json POST '/salary-templates' @{job_title='經理';salary_min=40000;salary_max=60000;data_source='測試用假資料，非市場統計'} $headers
$b = Send-Json POST '/batches' @{message='三個工程師、五個助理、一個除錯員、兩個經理，經理月薪十萬元'} $headers
# 經理保留 100000；其餘範本薪資必須由 HR 檢視後明確確認。
$b.items | Format-Table title,quantity,salary_min,salary_source,salary_confirmed
foreach ($i in $b.items) {
  $body = @{title=$i.title;quantity=$i.quantity;description=$i.description;requirements=$i.requirements;location=$i.location;salary_min=$i.salary_min;salary_max=$i.salary_max;salary_type=$i.salary_type;currency=$i.currency;confirm_salary=$true}
  Send-Json PUT "/batches/$($b.id)/items/$($i.id)" $body $headers
}
Send-Json POST "/batches/$($b.id)/confirm" @{} $headers
Send-Json POST "/batches/$($b.id)/publish" @{} $headers
Send-Json POST '/chat' @{message='經理月薪是多少？'} $headers
Send-Json POST '/chat' @{message='列出全部職缺'} $headers
Invoke-RestMethod "$base/job-postings" -Headers $headers
Invoke-RestMethod "$base/chat-logs" -Headers $headers
Invoke-RestMethod "$base/audit-logs" -Headers $headers
```

確認、刊登與登出端點無需 request body。聊天查詢只讀取已儲存的同公司資料；建立草稿須使用 `/batches`，查詢不會自動刊登。

## API 索引

| API | 用途 |
| --- | --- |
| POST /auth/register | 建立新公司及 HR，Email 全域唯一 |
| POST /auth/login、/auth/logout | 登入／撤銷目前 Token |
| GET /health | 健康狀態及已設定的 AI 模式（不會呼叫供應商） |
| GET、POST /job-templates | 公司職缺範本查詢／新增 |
| GET、POST /salary-templates | 具來源的薪資參考查詢／新增 |
| POST /chat | 自然語言查詢已刊登職缺及薪資資料 |
| GET /chat-logs、/audit-logs | 對話與操作紀錄，limit 1–200 |
| GET、POST /batches | 草稿批次查詢／建立 |
| GET /batches/{id} | 明細、薪資來源、缺漏欄位 |
| PUT /batches/{id}/items/{item_id} | 完整取代可編輯欄位、確認薪資 |
| POST /batches/{id}/confirm | HR 確認整批 |
| POST /batches/{id}/publish | 交易式刊登；已刊登重試回 409 |
| GET /job-postings | 已刊登的同公司職缺 |

薪資上下限須同時提供或同時為 null。草稿缺薪資可以儲存，但不能確認刊登。HR 變更薪資會記為 hr_explicit；編輯其他欄位不會抹掉既有薪資來源。公司無權讀取另一公司的批次時回 404。

## 認證與資料隔離

密碼以標準函式庫 scrypt 加隨機 salt 儲存。Bearer Token 為 256-bit 隨機值，資料庫僅存 SHA-256 摘要、有效期八小時，登出立即撤銷。這是 opaque token，並非 JWT。公司 ID 由登入身份取得，不接受客戶端任意指定。公司隔離由 API 查詢條件與批次父層歸屬檢查實作；資料庫管理者仍有完整存取權，未啟用 PostgreSQL RLS。

`ALLOW_REGISTRATION=false` 可停用開放註冊。MVP 不提供加入既有公司的邀請／管理介面；部署對外前需另加 TLS、登入限流、帳號管理、備份及紀錄保存政策。對話包含 HR 原文，不記錄密碼或 Token。操作紀錄為應用層紀錄，並非不可竄改的外部稽核儲存。

## OpenRouter AI 設定

已直接串接 OpenRouter `https://openrouter.ai/api/v1/chat/completions`，使用 httpx 及 JSON Schema structured outputs，不需另裝 OpenAI SDK。

1. 在 [OpenRouter](https://openrouter.ai/settings/keys) 建立 API key。
2. 將 現有 `.env` 保留並補齊以下設定；若原 `.env` 有 `LLM_MODE=rules`，請改成 `auto` 或 `openrouter`。
3. 重新啟動 FastAPI。金鑰只放後端 `.env`，不用貼到聊天或前端。

```dotenv
LLM_MODE=auto
OPENROUTER_API_KEY=填入你的金鑰
OPENROUTER_MODEL=openai/gpt-4.1-mini
OPENROUTER_TIMEOUT_SECONDS=20
```

模型 ID 可更換，需選擇支援 JSON Schema structured outputs 的模型／供應商。API 請求帶 `provider.require_parameters=true`；不支援、餘額不足或 key 錯誤會走安全 fallback。預設每次請求最多輸出 4000 tokens，沒有自動重試，避免重複付費。`httpx` 的 timeout 為連線／讀寫等階段逾時，並非整個 HTTP 請求的硬性總時限。

| LLM_MODE | 行為 |
| --- | --- |
| auto（預設） | 有 key 使用 OpenRouter；無 key 使用規則 |
| openrouter | 啟動時必須有 key；呼叫失敗仍嘗試規則 |
| rules | 強制離線，完全不呼叫外部 AI |

### AI 負責的功能

- `POST /batches`：模型擷取職稱、人數與 HR 已說明的工作內容、條件、地點。可以處理「經理需要兩位，經理的月薪是十萬元」等不同語序。文字欄位需可在原文找到，人數需有原文數字與人數單位；不接受模型杜撰內容。
- 薪資不交給模型產生。後端只接受可核對的「職稱月薪／時薪／年薪金額」原文，例如「經理的月薪是十萬元」。無法安全對應的薪資回 422 請 HR 改寫，不套用較低範本。若原規則可完整解析職稱及人數，模型也不能刪減或改動該結果。
- `POST /chat`：模型辨識查詢意圖與職稱，再由後端查詢、組織固定格式回覆。回答金額全部來自同公司資料庫；**不是自由生成長文或外部市場薪資調查**。不支援跨輪代名詞記憶，對話仍完整留存。
- 模型沒有資料庫寫入、執行程式或正式刊登工具；草稿仍需 HR 編輯確認。

啟用後，招募解析會將本次 HR 輸入傳到 OpenRouter 及其路由的模型供應商；查詢只傳本次訊息與同公司可用職稱（最多 500 個，超過改用規則），不傳資料庫薪資、密碼、登入憑證或歷史對話。不要在招募訊息中放入不必要的個資。此版本未設定 OpenRouter ZDR 或特定供應商資料政策。

### 結果與失敗處理

`/batches` 及 `/chat` 回傳 `ai`，操作紀錄也保存該次使用模式及 fallback 原因。例如：

```json
{"ai":{"mode":"openrouter","model":"openai/gpt-4.1-mini","fallback_reason":null}}
```

無 key、逾時、HTTP 401/429/5xx、拒答、截斷、JSON 或欄位驗證失敗時，嘗試規則解析；回應會顯示 `mode=rules` 及穩定的 fallback 原因代碼。供應商原始錯誤與金鑰不回傳、不寫入操作紀錄。規則也無法安全解析時回 422，**不建立部分草稿**。AI 本身辨識不清楚或薪資無法對應時也回 422。

無 key 時的規則格式仍為「三個／3位／五名 + 職稱」，不同職缺以頓號或逗號分隔，例如「三個工程師、兩個經理，經理月薪十萬元」。模型擷取會進行原文檢查，但不保證完全理解複雜中文，請 HR 在確認時檢視所有欄位。

## 資料表

`companies` 公司、`users` HR、`access_tokens` 登入憑證摘要、`job_templates` 公司職缺範本、`salary_templates` 具來源的公司薪資參考、`recruitment_batches` 草稿批次、`recruitment_batch_items` 招募明細、`job_postings` 正式刊登快照、`chat_logs` 對話、`audit_logs` 操作紀錄。明細與正式刊登透過唯一 batch_item_id 關聯，避免重複刊登。刊登後禁止編輯批次。工作內容、條件、地點與確認薪資皆為必填。

## 測試

```powershell
.\.venv\Scripts\python -X utf8 -m pytest tests/recruitment_backend -q
```

測試每例使用 `.test-data/` 下的獨立 SQLite 測試資料庫（不會被打包，可自行清理）。涵蓋多職缺中文數字／薪資解析、HR 指定十萬不被五萬覆蓋、薪資來源優先順序、建議薪資確認、未知薪資不虛構、認證登出、公司隔離、編輯撤銷確認、重複刊登，以及第二筆刊登失敗時整批與稽核回滾後可重試。PostgreSQL 連線格式已提供，但本次未連線驗證；亦未宣稱完成正式環境壓力測試。

OpenRouter 測試使用 `httpx.MockTransport`，不需真實 key、不產生模型費用。涵蓋結構化請求、原文核對、防模型更改薪資／刪減職缺、缺 key、逾時、401／429、無效 JSON、截斷、查詢公司隔離及 AI 草稿流程。本次未使用真實 OpenRouter key 呼叫供應商，實際模型可用性與帳戶額度仍須部署時確認。

## 實作參考

交易行為依 [SQLAlchemy Session 文件](https://docs.sqlalchemy.org/en/20/orm/session_basics.html) 的單一提交／例外回滾模式；Bearer API 整合參考 [FastAPI Security 文件](https://fastapi.tiangolo.com/tutorial/security/)。

OpenRouter 串接依 [認證文件](https://openrouter.ai/docs/api/reference/authentication) 與 [Structured Outputs 文件](https://openrouter.ai/docs/guides/features/structured-outputs)。

Windows 執行全套測試請使用 python -X utf8 -m pytest tests -q，避免原有測試讀取 UTF-8 紀錄時使用 CP950。


## PR22 整合驗證（2026-11-04）

- 最新 main 已整合，原 PR22 招募、模擬平台與 Computer Use 路由保留。
- 新批次 MVP 掛載於 `/api/recruitment/mvp`，與原 `/api/recruitment/*` 的驗證方式、資料庫及路由分開。
- Python 完整回歸：792 passed、1 skipped、31 subtests passed（58.79 秒）。
- 前端招募流程：13 passed；JavaScript 語法檢查與靜態站建置通過。
- `python -X utf8 -m pytest tests -q --tb=short -p no:cacheprovider`。
- 本次 OpenRouter 與瀏覽器外部服務使用測試替身，未重新執行付費模型／外站端到端操作；PostgreSQL 仍未連線驗證。
- GitHub Pages 已發布靜態展示站；沒有把 API key、履歷或本機資料庫放入公開網站。
