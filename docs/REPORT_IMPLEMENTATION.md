# 企業多區比較報告：實作與交接

實作日期：2026-10-27。開發分支：`codex/final-comparison-report`。基底為`codex/district-job-comparison`的`fe6a0b3`（含既有行政區比較；PR #20 尚未合併時，本次 PR 以該分支為 base）。

## 啟動與操作

完成 [README 的環境安裝](../README.md#快速開始)後，在本儲存庫根目錄執行：

```powershell
python -m uvicorn api.main:app --host 127.0.0.1 --port 8892
```

請先啟用已安裝專案依賴的 Python 虛擬環境。產品仍只使用原有FastAPI、pandas、numpy、requests等依賴；JSON Schema驗證是開發檢查，不是新增的線上服務。

開啟`http://127.0.0.1:8892/compare`。選2–3區、中類、職務、觀測時間及招募計畫，先確認期別再建立報告。可從首頁「比較招募環境」進入。

報告可查證每項觀察、規劃各月到職目標、針對固定快照追問，並開啟列印版／另存PDF或下載JSON。列印版使用瀏覽器列印功能，不新增PDF服務。

## 已完成的三項功能

### 企業報告

- 嚴格Scenario驗證與版本化選項，觀測期間與企業計畫分開。
- 沿用同交易的官方比較服務，支援固定職缺快照，不複製聚合算法。
- resolve固定捕獲值與manifest，再以resolution_token建立，避免確認與建立途中更新。
- Report、Idempotency結果與建置稽核同SQLite交易保存。
- 原頁、追問與匯出使用同一報告；來源更新只影響新報告。
- 未知、真零、樣本無命中與截斷下限分開；截斷不產生全區排名。
- 中文手機版、鍵盤操作、純文字來源呈現、逾時／失敗／重試狀態。

### GCIS對結論的影響

- 分開官方全市統計與行政區中類分類樣本。
- GS01–08控制全市方向、區域活動、證據不足、阻擋淨增及下一步查證。
- 原始清冊在唯讀捕獲中執行事件去重、衝突、前值與連續性檢查。
- 捕獲使用同一份解析bytes的hash；原下載hash與清理後檔案hash明確分開。
- 兩種觀察窗口獨立；回看使用目前留存版本，不冒充當時可知資訊。
- 缺分類時只讀本窗必要清冊；有分類時才重建必要歷史資本鏈，避免每份報告反覆處理整批歷史。

### 事實一致性與AI

- 後端建立FactLedger、用途Assessment與ClaimCatalog，模型不能新增值或自由結論。
- AI只選本報告claim_id及白名單heading_id；跨報告、錯catalog、額外文字皆拒絕。
- Renderer統一產生地區、指標、數量、單位、期別、來源及必要限制。
- 無key／provider故障或兩次不合法計畫時使用受控標準解說，不冒充模型成功。
- request_id串起事件，保存問題hash、版本、實際回傳model與可取得的token統計，不存原始敏感問題或錯誤模型文字。
- render_contract_hash固定Renderer、指標／限制登錄與模板。舊報告可讀／匯出；顯示規則不相容時不重新用新模板解說，要求建立新版。

這些保證只適用核准快照／規則一致性，不是來源真實性或企業招聘成功的保證。

## 目前資料的實際限制

本次驗收使用的資料副本具備483份GCIS原始清冊，但缺少正式稅籍精簡檔及完整營業項目→行業對照。原始清冊不足以自行認定公司屬某製造中類；重新下載的儲存庫或其他資料版本不保證具備相同資料量。

因此：

- 官方全市製造業2025-09至2026-08新設916家，對照2024-09至2025-08的1088家，變化約−15.81%，可按這些觀測期與原統計範圍描述；不代表持續更新的即時結果。
- 區域正式新設／資本增加／解散數值保持UNKNOWN，可點查缺分類與來源原因。
- 8列既存區域聚合樣本另外保留在`legacy_observations`，不冒充新canonical計數或母體。
- 工廠分類08–33可精確對應現有26類；34缺少精確對應，保留未知。
- 36,201.78元的薪資是2025-12臺中製造業C、單位類別1、參加就保註記1的平均投保薪資；不是所有受僱者或實領薪資。

後續取得有來源的稅籍／營業項目對照，放到既有ETL規定位置後，GCIS樣本Adapter即可啟用。內部`classification_map`注入供隔離測試使用，不是公開API讓使用者自行貼產業標籤。

人才培育管線與全市預測圖屬原設計選配，本次不新增未驗證推估。正式報告不使用舊模擬錯配工具。

## 資料保存與設定

預設新資料庫是`database/comparison_reports.sqlite3`，不修改原始`mismatch_system.db`。可用`COMPARISON_REPORT_DB`指定其他路徑。檔案已加入gitignore。

首次寫入自動建立resolve、report、idempotency及event表。來源仍在既有SQLite／CSV；捕獲的結果與來源manifest一起保存，建立報告後不重查latest。此MVP使用不可變JSON發布快照，而非另部署資料倉儲或物化全部歷史事件表。

resolve權杖有效15分鐘。相同Idempotency-Key與請求可讀回原commit，即使權杖之後過期；不同請求使用同key回409。

報告AI沿用`OPENROUTER_API_KEY`與`OPENROUTER_MODEL`。模型需在`REPORT_ASSISTANT_ALLOWED_MODELS`白名單，且本版只接受固定OpenRouter API端點。預設白名單與既有模型設定一致；不需key也能建立報告。

上述啟動命令只綁127.0.0.1。若之後公開部署，應先套用登入／報告存取權、流量與成本政策；UUID本身不是授權。

## API

| 方法與路徑 | 功能 |
|---|---|
| GET `/api/comparison-options` | 區域、中類、可用時間與規則版本 |
| POST `/api/reports/expansion-comparison/resolve` | 接Scenario，回固定期別與resolution_token |
| POST `/api/reports/expansion-comparison` | 接`{scenario,resolution_token}`及Idempotency-Key，成功201 |
| GET `/api/reports/{id}` | 原報告與固定來源／事實／主張 |
| POST `/api/reports/{id}/questions` | 接`{question}`，回受控blocks與ai_status |
| GET `/api/reports/{id}/export?format=html` | 同版本列印頁 |
| GET `/api/reports/{id}/export?format=json` | 同版本JSON |

錯誤：422輸入無效；409條件／權杖／顯示契約不符；404報告不存在；503來源讀取、事實一致性或必要保存／稽核失敗。

## 驗證

```powershell
python -X utf8 -B -m pytest tests -q --basetemp tmp/report-verification -p no:cacheprovider
node --check ui/static/report-comparison.js
```

Windows受限環境若無法建立asyncio本機socketpair，既有API測試可能停在事件迴圈初始化；這是執行環境問題。新測試另有不需socket的同步ASGI驗收；完整測試需在允許本機迴圈socket的終端執行。

2026-10-28 PR前完整回歸：**494項通過，30.97秒**。正式資料冒煙與JSON Schema驗證通過，來源資料庫雜湊在操作前後一致。驗證1個Scenario、27個Fact、61個Claim、4個Assessment與1個AnswerPlan。

PR前檢查另修正三項可重現問題，均有回歸覆蓋：異常provider envelope改走受控備援；GCIS與薪資排除未來觀測期，歷史回看也排除尚未發生的清冊月份；前端共同背景只呈現核准blocks，不能回填未進FactLedger的原值。

2026-10-27桌面1280×900及手機390×844已完成實際建立報告、來源查閱與備援追問確認，無頁面水平溢出；寬表格保留容器內捲動，瀏覽器無console錯誤。PR前前端修正另以實際renderCity函式的Node DOM回歸確認。

- [機器可讀驗收記錄](../reports/comparison_report_validation.json)
- [桌面截圖](../reports/comparison_report_desktop.png)
- [手機截圖](../reports/comparison_report_mobile.png)

驗收報告ID只存在驗收用的本機資料庫，其他環境無法讀取。請在自己的 `/compare` 建立報告，再使用建立後的 `/reports/{report_id}` 網址；上方截圖與機器可讀記錄供核對當次驗收結果。

測試包含官方來源形狀的隔離資料、mock模型、錯誤變異與真實資料冒煙；不把mock通過率稱為真實模型準確率。模型金鑰未設定，真模型任務與企業實際試用仍待驗收；區域GCIS分類來源缺口與補齊方式見上方資料限制。
