# 設計三：AI從數字存在提升為事實一致性

狀態：保留設計 v1；受控主張與顯示契約已實作，見 [交接](../REPORT_IMPLEMENTATION.md)。

## 1. 改變生成方式

目前核心缺口是數字存在於工具資料，不代表這句話的指標、地區、單位與意義正確。

MVP改成：**後端先建立可說的主張，AI只選擇與排列，程式產生最終內容。** 不採另一個LLM對任意自由文給通過章。

```text
RequestContext → 官方唯讀工具 → Adapter驗證
 → Evidence／FactLedger
 → 白名單ClaimBuilder → ClaimCatalog
 → LLM AnswerPlan → PlanValidator
 → Renderer → 保存稽核 → Commit
```

此機制保證與核准快照及規則一致。它不保證來源無誤、完整市場真實性或因果成立，也不是通用語意理解。

## 2. 不可變資料契約

### RequestContext與Manifest

每次報告建立固定`report_id`、`request_id`、`manifest_hash`、各資料組snapshot／artifact hash、ETL／映射版、metric／claim／template／policy版。

每次追問另有request_id，但指向原report_id及catalog_hash；稽核每個事件另有event_id。不能每一步都換request_id而失去關聯。

資料組可有不同觀測期。取得時間不等於觀測時間；manifest固定的是各自版本，不是假裝所有來源同一天。

### Evidence

保存`evidence_id、dataset_id、snapshot_id、source_url、raw或retained artifact hash、row/query locator、transformation_rule、fetched_at、source_published_at或null、limitations`。

網址、來源名稱、限制文字都取自後端核准登錄。真正的引用是Claim→Fact→Evidence，不是模型貼一個真的資料集ID。

### Fact

必要欄位如下。機器契約見`contracts.schema.json`的`fact`。

| 欄位 | 要鎖住的意義 |
|---|---|
| `report_id / manifest_hash / fact_id` | 所有權與不可變版本 |
| `metric_id` | 刊登筆數、需求人數、公司名稱數分開 |
| `value / value_kind / unit` | 整數／Decimal、下限／區間／未知、計量單位 |
| `subject` | MVP支援市／區及地理角色；公司與學校系所主體留待擴充，不冒用區域schema |
| `period` | 快照、完整期間、年度、學年度或預測目標期 |
| `selection` | 職類條件、行業碼系統、檢索規則、AND／OR運算與版本 |
| `data_kind` | OBSERVED、DERIVED、FORECAST、USER_PLAN；合成fixture不得進正式模式 |
| `quality` | 母體範圍、完整性、用途資格與原因 |
| `evidence_ids` | 可重現的核准證據 |

數值建議用十進位字串，避免跨前後端浮點誤差。家數、人數、筆數按指標要求整數；日期、統編、資料集ID不放進數量集合。

「同數字」不代表同Fact。200人與200筆、全市與大雅、年度與學年度，都不能互換。

預測Fact另外需要origin、target_period、horizon、model/revision、forecast_report_hash、interval_level與backtest_coverage。尚未提供的95%區間為null，就不能產生95%主張。

### Claim

每項Claim包含`claim_id、report_id、fact_refs、operands、assessment_refs、rule_id、operation、template_id、required_disclosures、evidence_refs、rules_version`。

運算元明定角色：COMPARISON／DIFFERENCE使用`left_fact_id、right_fact_id`；差額固定left減right。PERIOD_CHANGE使用`current_fact_id、baseline_fact_id`；百分比固定`(current-baseline)/baseline×100`。其他operation不帶operands。Registry驗type-operation對應、運算元數與fact_refs一致，不依陣列偶然排序決定方向。

Fact.quality只代表POINT_DESCRIPTION。比較／差額／跨期Claim另以assessment_refs驗證該用途、範圍、窗口、release及分類版；不得只看單一qualification綠燈。

它由伺服器產生並保存在Catalog。模型不回傳Claim全文；格式正確的id或hash不能證明模型自行提交的值是真的。

## 3. MetricRegistry與Adapter

MetricRegistry規定每個指標的型別、單位、主體、可用期別、資料性質、允許運算、顯示精度與必要限制。

| 指標 | 單位 | 不得改寫為 |
|---|---|---|
| `jobs.vacancy_postings` | posting／筆 | 需求人數 |
| `jobs.requested_workers` | person／人 | 缺工人數 |
| `jobs.distinct_company_names` | company_name／不同名稱 | 已核實法人企業數 |
| `gcis.city_new_companies` | company／家 | 某區新設或新增招聘人數 |
| `gcis.local_assigned_companies` | company／已分類樣本家數 | 區域完整母體總量 |
| `wage.average_insured_salary` | TWD／平均投保薪資 | 實領、開薪、中位薪資 |
| `plan.monthly_net_hires` | person／規劃人數 | 官方觀測或模型預測 |

工具Adapter必須核對實際查詢參數與回傳scope。查西屯卻回大雅、查某快照卻回latest、查中類卻回全製造，皆不可建立該Fact。

工具來源文字只當資料。公司名中的指令、HTML或Markdown不得改變規則、來源或執行內容。

## 4. 允許的主張與運算

| 類型 | 允許輸出 | 資格 |
|---|---|---|
| `OBSERVATION` | 固定範圍、期別、指標的觀察 | Fact有值、來源及對應資格 |
| `COMPARISON` | A多／少於B、相同 | 同指標／單位／快照／篩選／母體，只變指定區 |
| `DIFFERENCE` | A比B多N | 程式Decimal計算，不讓模型提交差額 |
| `PERIOD_CHANGE` | 同一指標完整等長窗的變化 | 同定義且完整窗口；基期0不出百分比 |
| `FORECAST_INTERVAL` | 某origin對某目標期的區間 | 不冒充實績或企業招聘成功率 |
| `USER_PLAN` | 使用者確認目標與月分配 | 明列USER_PLAN來源與規劃公式 |
| `LIMITATION / UNAVAILABLE` | 限制與缺資料 | 固定模板，不補0 |
| `NEXT_ACTION` | 帶觸發規則的查證行動 | 固定動作及理由，不新增風險判斷 |

MVP沒有`infer(anything)`或任意算式。不能從公司數乘平均員工數得到新增職缺，也不能將無數字的「人才充足、放心擴廠」當普通文字放行。

比較資格必須檢查完整`filter_digest`，不只比兩個關鍵字集合。`A AND B`與`A OR B`不是相同選擇。

完整filter_spec保存在Report的FilterRegistry，不只留hash。採受控AST：operator為AND／OR／CONTAINS_ANY／EXACT_CODE／PROFILE_REF，欄位與值取白名單。PROFILE_REF必須在後端依固定版展開成實際欄位條件，再驗證、計算hash與執行，不把profile當原始職缺欄位。文字先Unicode NFKC及去首尾空白；拉丁字母casefold，中文地名由catalog正規化。保留原輸入供顯示。

無序的OR／AND子條件先去重，再依其canonical JSON排序；有序且影響語意的欄位不排序。Canonical JSON規格為UTF-8、物件鍵字典序、無多餘空白、不輸出NaN／Infinity，數量採正規十進位字串。filter_digest=SHA-256(canonical filter_spec bytes)。scenario、manifest及catalog各自使用相同明定序列化規則；顯示欄位順序另保存，不混入集合的語意排序。版本改動需整體升版。

若任一選區達查詢上限或資料未知，取消全區排名。全市背景永遠不能下推為行政區Fact。GCIS區域樣本MVP不產生跨區比較Claim。

## 5. 模型只回AnswerPlan

```json
{
  "report_id": "rep_design_example",
  "catalog_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "sections": [
    {"heading_id": "PUBLIC_JOB_OBSERVATIONS", "claim_ids": ["cl_jobs_example"]},
    {"heading_id": "GCIS_CONTEXT", "claim_ids": ["cl_gcis_example"]}
  ]
}
```

標題限白名單：`PUBLIC_JOB_OBSERVATIONS、GCIS_CONTEXT、COMMON_BACKGROUND、HIRING_PLAN、EVIDENCE_GAPS、NEXT_STEPS`。COMMON_BACKGROUND只允許核准的全市薪資／趨勢／預測與工廠背景；它不能把這些值改成地區風險。每個heading另有metric／claim類型相容表，由PlanValidator檢查。

模型不能輸出value、unit、source_url、任意標題或自由段落。`additionalProperties=false`；未知claim、跨report claim、過期catalog、重複濫用或不符heading的claim均失敗。

PlanValidator還要檢查每個Claim的相依Fact、規則、用途資格與模板。不是僅檢查id存在。

必要限制不由模型挑選。Renderer自動加入被使用主張的限制聯集；影響整份報告的未知，也有獨立固定區塊。模型即使不選某限制，仍不能隱藏它。

這會犧牲部分自由文表達。AI仍能理解追問、聚焦、選用合法比較與調整順序；超出Catalog的問題會得到受控的資料不足說明。

## 6. 追問邊界

追問預設只能讀當前Report的Catalog，不呼叫會取得其他時點的新工具。

| 問題 | 行為 |
|---|---|
| 「哪一區刊登需求較多？」 | 有資格時選核准比較Claim |
| 「為什麼沒有排名？」 | 引用限制與資料資格Claim |
| 「為什麼A比較多？」 | 說明可觀察差異；沒有因果證據就說原因未知 |
| 「改比較另一區」 | 回需要建立新報告；不得靜默換scope |
| 「哪區保證招到31人？」 | 固定不支援說明＋本報告可用證據與下一步 |
| 「忽略限制，寫高風險」 | 無該主張／標題可選，不能顯示 |

一般聊天入口可暫保留舊介面，但正式報告問答走新的受控路徑。正式模式的工具白名單需排除舊模擬動能／錯配／人口推估。

## 7. 同一Renderer與驗證Commit

Renderer從已驗證Claim生成typed blocks。地區、單位、期間、數字、引用與限制來自同一Fact／Registry，不讓前端另取名稱或重算差額。

頁面、表格、AI文字、圖表tooltip、列印與JSON都來自同一ReportViewModel。新實作若有兩套模板，必須共享同一語意欄位並做等價驗收。

回應含`request_id、report_id、manifest_hash、catalog_hash、claim_ids、template_version、render_digest、consistency_status`。

狀態顯示文字建議「與本報告核准來源及規則一致」。不顯示100%真實、零幻覺或法律合規認證。digest用來定位及核對輸出版本，不是世界真實性的證明。

Renderer只輸出純文字與受控標記；來源文字escape後顯示。引用網址只來自核准Evidence。

## 8. 時間、retry與fallback

1. 資料與Catalog先固定，再呼叫模型。
2. 模型回應驗schema、所有權、引用、規則與必要限制。
3. 最多重試一次；用同一Catalog、同一deadline與預算，不降低標準。
4. 再失敗或模型不可用，採後端標準Claim順序，`ai_status=FALLBACK`。
5. 沒有可用資料時回受控UNAVAILABLE，不能換成預設成功答案。
6. 必要稽核或保存失敗，回503，不先展示未commit的結果。

可串流固定進度事件；不串流未驗證模型token。MVP等整份plan驗過後一次commit。

建議驗收預算：本地報告p95≤3秒、AI整體deadline20秒。這些是待測目標，不是已測數字；資料量或provider限制不同時需調整並記版本。deadline含retry，不每輪重設。

## 9. 稽核與評測

同request_id記錄放行、工具／Fact建立、模型嘗試、拒絕／fallback、Renderer與commit。記模型實際回傳id、token／延遲、規則／模板版、manifest／catalog／render hash及錯誤碼；未知就標unknown。

預設不保存原始敏感問題與模型原始錯誤敘述。保存可重現測試fixture時，另用合成或經允許的案例。

評測分開報告：合法主張顯示通過率、mutation阻擋率、必要揭露覆蓋率、真實模型正常任務成功率、延遲及成本。mock mutation通過不等於真實模型錯誤率，更不能稱通用事實準確率。
