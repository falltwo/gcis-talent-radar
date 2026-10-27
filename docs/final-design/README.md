# 三項決賽功能設計總規格

日期：2026-10-27（Asia/Taipei）

狀態：**設計 v1；三項核心已完成本機MVP實作**。本文保留設計決策與原規劃；實際交付、API與尚缺資料見 [實作交接](../REPORT_IMPLEMENTATION.md)。
基準：主線 `e0cf78cec3d995e6402d2eff938179cfcd8994ad`；行政區比較分支 `fe6a0b37d7acf162a272f322495628e898a49d2d`。

## 交付內容

| 設計 | 開發規格 |
|---|---|
| 企業多區比較報告 | [01-enterprise-report.md](01-enterprise-report.md) |
| GCIS 影響產品結論 | [02-gcis-conclusions.md](02-gcis-conclusions.md) |
| AI 從數字核對到事實一致性 | [03-fact-verification.md](03-fact-verification.md) |
| 實作順序、工作包與驗收 | [04-delivery-and-acceptance.md](04-delivery-and-acceptance.md) |
| 輸入與 AI 輸出契約 | [contracts.schema.json](contracts.schema.json) |
| 具體設計範例 | [examples.synthetic.json](examples.synthetic.json) |
| 可視化閱讀 | [design.html](design.html) |

先前規劃階段僅新增設計文件。後續依使用者指示完成核心程式，採獨立報告資料庫，不更新原始官方資料庫；尚未推送或部署。

## 一個產品，三個相依層

三項工作共同產出「**企業擴廠招募環境比較報告**」。使用者比較 2–3 個臺中行政區，查看同職類的公開刊登、同業公司事件與證據限制，再帶走一份可保存、可追問的報告。

```text
企業確認情境
  → 固定各來源快照與版本
  → 官方資料 Adapter
  → FactLedger：含範圍、期別、單位的事實帳本
  → GCIS與比較規則：判斷可說什麼
  → ClaimCatalog：核准主張清單
  → 固定摘要／AI選擇與排列主張
  → 同一 Renderer 產生頁面、解說及匯出
```

**報告建立不依賴大模型。** 沒有金鑰或模型不可用時，查詢、規則摘要、來源與列印仍可用。AI 的工作是理解追問、選重點及排序；核心事實與結論由核准資料和規則提供。

## 本設計先採用的決策

| ID | 建議決策 | 理由與代價 |
|---|---|---|
| D01 | MVP 比較 2–3 區、單一製造業中類、單一職類檢索條件 | 能沿用既有比較服務；多職類、多中類另開版本 |
| D02 | 觀測月份與招募起迄月份分開 | 查詢過去／當期資料與規劃未來是不同工作 |
| D03 | 每個資料組各自標期別，同指標跨區才要求一致 | 工廠、職缺、GCIS及薪資本來就不同頻率 |
| D04 | 招募人數只影響企業規劃區塊 | 沒有足夠證據把人數換成招聘成功率 |
| D05 | GCIS 分官方全市統計與區域已分類樣本 | 兩種母體定義不同，不能混用 |
| D06 | 品質狀態真的控制可產生的主張 | 不只加警語，還要停用不成立的排名與推論 |
| D07 | 正式報告的工具白名單排除模擬來源 | 不讓自由追問退回舊錯配數字 |
| D08 | AI 只輸出 claim_id 與 heading_id | 能在數天內封住換區、換單位及無證據結論 |
| D09 | 報告、事實、主張、模型追問與匯出共用版本 | 防止 ETL 更新後出現互相矛盾的內容 |
| D10 | MVP 以瀏覽器列印產生 PDF，另匯出 JSON | 不新增 PDF 服務或佇列依賴 |
| D11 | 不產生總風險分數、不推薦唯一最佳地點 | 先交付有依據的比較及查證工作，避免偽精準 |

使用者已指示依設計逐項實作。具體實作取捨與驗收結果另記於實作交接；改動契約時仍須同步更新規格與驗收。

## 共用名詞與保證範圍

| 名詞 | 定義 |
|---|---|
| Scenario | 使用者確認的地區、中類、職類、觀測時間與招募計畫 |
| SourceManifest | 每個來源固定的檔案／資料庫快照、取得時間、雜湊與 ETL 版 |
| Evidence | 指向原始來源、轉換規則及可重現列集合的證據 |
| Fact | 一項指標與其數值、單位、主體、篩選、期別、資料性質 |
| Claim | 後端依白名單規則產生、可以顯示的一項陳述 |
| AnswerPlan | AI 從本報告 ClaimCatalog 選出的顯示順序 |
| Report | Scenario、Manifest、Facts、Claims 與所有必要限制的不可變集合 |

「事實核驗通過」只表示：**輸出與本報告核准的資料快照、計算及模板一致**。它不證明來源沒有錯、不證明代表全市場，也不證明企業事件造成缺工。

## 共用狀態設計

不要用一個 `success=true` 同時表示系統正常、資料完整、比較有效與招聘可行。

| 軸 | 值 | 用途 |
|---|---|---|
| `build_status` | `COMPLETE / FAILED` | 報告是否完成建置與保存 |
| `data_status` | `USABLE / LIMITED / UNAVAILABLE` | 核心資料能否使用；LIMITED不代表產品壞掉 |
| `qualification` | `QUALIFIED / PARTIAL / UNAVAILABLE` | 某項資料對指定用途是否足夠 |
| `value_status` | `EXACT_WITHIN_SCOPE / LOWER_BOUND / SAMPLE_MATCH_ZERO / UNKNOWN` | 數值應如何解讀 |
| `comparison_status` | `COMPARABLE_SAMPLE / DESCRIPTIVE_ONLY / NOT_COMPARABLE` | 是否能產生跨區／跨期大小與差額 |
| `ai_status` | `NOT_REQUESTED / VERIFIED / FALLBACK / BLOCKED` | AI 計畫與顯示狀態 |

真正的零可用 `EXACT_WITHIN_SCOPE` 且 value=0。`SAMPLE_MATCH_ZERO` 只表示已分類樣本無命中；`UNKNOWN` 的 value 一律為 null。各軸由伺服器計算，不接受模型指定。

`data_status`只依官方資料聚合，不把USER_PLAN算成可用資料：職缺與GCIS為核心組。兩組對本次已承諾用途均有可用描述、且無阻止該用途的缺口，才為USABLE；至少一個官方組可描述但核心不齊或資格受限，為LIMITED；沒有官方組可描述，為UNAVAILABLE。來源正常的市場邊界仍須揭露，USABLE不是全市場完整。

`ai_status`屬每次AnswerEvent／QuestionResponse，不寫回不可變Report。追問只追加事件，不能改原payload/hash。

`LOWER_BOUND`只適用能證明為同scope子集合的觀測，例如被查詢上限截斷的公開職缺。GCIS分類樣本可能錯分，不能標為真實歷史產業母體下限；它只對指定分類規則的樣本數使用EXACT_WITHIN_SCOPE、SAMPLE_MATCH_ZERO或UNKNOWN。

## 範圍與取捨

本次必做：正式比較入口、固定快照、GCIS 規則摘要、事實／主張綁定、受限 AI 追問、列印與 JSON、正常與反例驗收。

本次設計也定義工廠、全市趨勢、薪資與人才培育管線的接入邊界。某模組沒有可信 Adapter 時，保留「尚不可用」，不阻止其他模組成為可用報告。

現有年度預測若接入，只能作全市背景，保留原起點與區間。人才培育資料需完成職類對照後才能接入；這不是三項設計上線的強制相依。

## 三項工作各自的完成定義

1. **企業報告：** 同一情境可產生比較、證據、計畫與匯出；資料更新後重新開啟仍相同。
2. **GCIS加值：** 固定其他來源，只改GCIS，摘要、被允許的比較或查證行動會依規則改變；不改寫職缺數，也不生成缺工機率。
3. **事實核驗：** 換區、換單位、換期別、跨報告引用、樣本冒充母體或無證據擴廠保證，不能出現在已核驗的正式輸出。

## 來源與設計依據

- 現有實作：`engine/official_labor_market.py`、`engine/expansion_demo.py`、`etl/sources/gcis_registry.py`、`agent/llm_agent.py`、`agent/numeric_verifier.py`，以上均以版本封面為準。
- 現有品質報告：`reports/DATA_QUALITY.md`、`docs/FORECAST_ENGINE.md`、`docs/SIMULATED_DATA.md`。
- 台灣就業通欄位及單次最多1,000筆的來源限制，已查[官方資料集44062](https://data.gov.tw/dataset/44062)。這是來源查詢上限，不代表能無限制分頁取回全部市場資料。
- 契約採用 [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)。Schema 驗形狀；月份順序、資料所有權、比較資格與公式仍須由程式驗證。

完整工作包與反例請依 [04-delivery-and-acceptance.md](04-delivery-and-acceptance.md) 驗收。本次文件中的數值範例均標示為合成設計資料，不當成真實產品成果。

## 本次文件與契約檢查

- JSON Schema Draft 2020-12 meta-schema檢查通過。
- Scenario、Fact、Assessment、Claim、AnswerPlan共5個正常範例通過schema驗證。
- 12個形狀／型別反例被拒絕，包含自由文字、非法標題、重複行政區、錯誤月份、樣本冒充母體下限、未知值帶數量、未定義預測及錯誤運算元。
- Markdown內部連結已核對；HTML有8個閱讀區段，生成器文字檢查0警告。
- 42項產品／資料／語意／故障場景是後續實作驗收規格，尚未執行；schema通過不能代替應用層語意驗證。
- 瀏覽工具拒絕本機file協定，未完成寬窄畫面自動預覽。沒有改用其他瀏覽方式繞過限制；HTML可由使用者直接開啟。
