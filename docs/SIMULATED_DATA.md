# 模擬資料清單（只標記，還不能刪）

repo 裡有幾張表是早期用模擬、寫死或推估補值做出來的。**不要當成真實數字使用，也不要在簡報裡當真實數字講。**

> ⚠ **現在只能標記，不能刪。** `api/main.py`、`agent/tool_router.py`、前端 `ui/index.html` 和 `benchmark/` 都還在讀這些表，刪了系統會直接壞掉。
> 要等後續 PR 一份份換成真實資料，**確認全文搜尋已經找不到任何程式在讀**，才能刪。

## 讀取方式要先知道

API 和助理讀的**不是 CSV**，而是 SQLite 資料庫 `database/mismatch_system.db` 裡的同名資料表。CSV 和資料表是同一支程式一起寫出來的（`df.to_csv(...)` 加上 `db.write_df(...)`）。所以：

- 替換時兩邊都要處理：產生程式、資料庫表、CSV。
- 下表的「讀取者」是用表名全文搜尋 `*.py`、`*.sql`、`*.html` 得到的（2026-10-05，`main` 分支 `ae8adbf`）。

## 總覽

| 表（CSV／資料庫表） | 產生程式 | 資料怎麼來的 | 主要讀取者 | 替代的真實表（#5） |
|---|---|---|---|---|
| `data/processed/companies_taichung_cleaned.csv`／`companies` | `etl/extract_gcis_batch.py` | **模擬** | API `/api/overview`；助理 `COMPANY_VERIFY`；`engine/gcis_live_verifier.py` | 尚無一對一替代（見下方） |
| `data/marts/industry_dynamics_mart.csv`／`industry_dynamics_mart` | `etl/extract_gcis_batch.py` | **模擬** | API `/api/overview`、`/api/industry-dynamics`、`/api/spatial-demand`；助理 `DISTRICT_QUERY`、`INDUSTRY_QUERY` | 部分替代：`tc_company_by_industry_monthly`、`tc_factory_district_industry_annual`、`tc_factory_count_district_monthly` |
| `data/marts/industry_momentum_mart.csv`／`industry_momentum_mart` | `engine/industry_momentum.py` | 由模擬資料**計算** | API `/api/industry-dynamics`；助理 `INDUSTRY_QUERY`；`engine/mismatch_engine.py` | 尚無替代 |
| `data/marts/mismatch_signal_mart.csv`／`mismatch_signal_mart` | `engine/mismatch_engine.py` | 由模擬資料與推估**計算** | API `/api/overview`、`/api/mismatch`；助理 `MISMATCH_QUERY` | 尚無替代 |
| `data/marts/industry_supply_mart.csv`／`talent_supply_mart` | `engine/talent_supply.py` | 由**推估補值**與未驗證規則計算 | API `/api/talent-supply`；助理 `SUPPLY_QUERY`；`engine/mismatch_engine.py` | 尚無替代 |
| `data/marts/department_indicators_mart.csv`／`department_indicators_mart` | `etl/extract_moe_udb.py` | 在學人數是真的；新生數、註冊率補值、117 學年推估是**推估補值** | API `/api/overview`、`/api/talent-supply`；助理 `SUPPLY_QUERY`、`DEPARTMENT_QUERY`；`agent/intent_router.py`；`engine/talent_supply.py` | 部分替代：`tc_udb_dept_annual` |
| `data/marts/dept_ucan_industry_mapping.csv`／`ucan_mapping_mart` | `etl/map_ucan_careers.py` | **未經驗證的人工規則**（不是模擬，但也不是官方對照，見下方） | API `/api/talent-supply`；助理 `SUPPLY_QUERY`；`engine/talent_supply.py` | 尚無替代 |
| `data/processed/demographics_projection.csv`／`demographics_projection` | `etl/extract_demographics.py` | **寫死在程式裡** | API `/api/talent-supply`；助理 `DEMOGRAPHIC_QUERY`；`etl/extract_moe_udb.py` | 尚無替代 |

以下也會讀到這些表，替換時要一起改：

- `benchmark/run_benchmark.py`：65 題基準測試的標準答案就是從這些表算出來的。
- `tests/test_etl_quality.py`
- `tests/test_official_data_tools.py`：檢查 `companies`、`industry_dynamics_mart`、`department_indicators_mart` 不得出現寫死的更新日期。

## 各表說明

### `companies_taichung_cleaned.csv`／`companies`

- **怎麼來的**：
  - 約 25 家知名企業寫死在程式裡，設立日一律是 1998-05-12，變更日 2024-03-15。
  - 其餘公司名單取自 104 職缺資料：
    - 統編用 `50000000 + hash(公司名稱) % 40000000` **合成**。
    - 資本額用 `random.choice` 從 5 個值裡**隨機**挑。
    - 地址的門牌號碼**隨機**。
    - 是否增資用 `random.choice([0, 0, 1])`。
    - 產業別是看公司名稱有沒有關鍵字（例如「軟體」→ ICT）。
- **讀取者**：
  - `api/main.py` `/api/overview`：公司總數。
  - `agent/tool_router.py` `COMPANY_VERIFY`。
  - `engine/gcis_live_verifier.py`：先查本地表，查不到才打 GCIS API。
  - `benchmark/run_benchmark.py`
- **替代**：尚無一對一替代。
  - 個別公司查核應直接用 GCIS API（`engine/gcis_live_verifier.py` 已有呼叫，不要再先查這張表）。
  - 家數統計請改用 `tc_company_by_industry_monthly`。
  - 注意：`agent/llm_agent.py` 已規定來源為 `104_GCIS_LINKED`、`GCIS_BENCHMARK` 的必須說「未核實」。

### `industry_dynamics_mart`

- **怎麼來的**：`build_industry_dynamics_mart()` **完全沒有讀任何登記資料**。
  - 總存量設成 118,000 家，再依寫死的行政區比例、產業比例分配。
  - 每個產業的新設率、增資率、退出率是寫死的參數（例如 ICT `entry_base: 0.088`），再加 `np.random.normal` 雜訊。
- **讀取者**：
  - `api/main.py`：`/api/overview`（113 年總存量）、`/api/industry-dynamics`、`/api/spatial-demand`。
  - `agent/tool_router.py`：`get_district_industry`（`DISTRICT_QUERY`）、`INDUSTRY_QUERY`。
  - `engine/industry_momentum.py`
  - `benchmark/run_benchmark.py`、`tests/test_etl_quality.py`
  - 前端：產業動態頁、臺中 29 區地圖頁。
- **替代**（#5，都只是**部分**替代，粒度不同，不能直接換表名）：
  - 全市 × 行業大類 × 月的新設、解散、現有家數 → `tc_company_by_industry_monthly`
  - 行政區 × 製造業中類 × 年的工廠家數、從業員工 → `tc_factory_district_industry_annual`
  - 行政區 × 工廠產業類別的最新月快照 → `tc_factory_count_district_monthly`
  - 行政區 × 中類的新設、增資公司數 → `tc_mfg_company_events_monthly`（**產業別定義待決**，見 #5）
  - 原表的「7 大目標產業」是自訂分類，跟行業標準分類對不上，替換時要重新定義產業。

### `industry_momentum_mart`

- **怎麼來的**：用 `industry_dynamics_mart`（模擬）算新設率、增資率，再做 Z-score 合成「需求動能」。方法本身沒有問題，但**輸入是模擬的**，所以結果也不能用。
- **讀取者**：`api/main.py` `/api/industry-dynamics`；`agent/tool_router.py` `INDUSTRY_QUERY`；`engine/mismatch_engine.py`；`benchmark/run_benchmark.py`
- **替代**：尚無替代。之後可改用 `tc_company_by_industry_monthly` 重算，但要先決定產業分類與指標定義。

### `mismatch_signal_mart`

- **怎麼來的**：需求動能（`industry_momentum_mart`，模擬）減供給動能（`talent_supply_mart`，推估），再分高中低預警。前端「供需錯配四象限」和 README 的錯配表都是這張。
- **讀取者**：`api/main.py` `/api/overview`、`/api/mismatch`；`agent/tool_router.py` `MISMATCH_QUERY`；`benchmark/run_benchmark.py`；`tests/test_official_data_tools.py`（只檢查更新時間欄位）
- **替代**：尚無替代。

### `industry_supply_mart.csv`／`talent_supply_mart`

- **怎麼來的**：系所學生數（`department_indicators_mart`）乘上 UCAN 對照權重（`ucan_mapping_mart`），加總到 7 大產業。117 學年的推估用到寫死的人口數。CSV 檔名是 `industry_supply_mart`，資料庫表名是 `talent_supply_mart`。
- **讀取者**：`api/main.py` `/api/talent-supply`；`agent/tool_router.py` `SUPPLY_QUERY`；`engine/mismatch_engine.py`；`benchmark/run_benchmark.py`；`tests/test_etl_quality.py`
- **替代**：尚無替代。輸入可改用 `tc_udb_dept_annual`、`tc_vocational_dept_annual`，但「系所 → 產業」的對照表還沒有可信版本。

### `department_indicators_mart`

- **怎麼來的**：
  - **真實部分**：各系所在學人數，來自教育部 UDB 原始 CSV。
  - **推估補值**：
    - `freshmen_admitted` = 在學人數 ÷ 4（不是實際新生數）。
    - 註冊率沒有資料時補 92.5。
    - `projected_students_117` 用寫死的人口比例（`extract_demographics.py`）乘上占比、註冊率趨勢外推。
- **讀取者**：
  - `api/main.py`：`/api/overview`（系所數、學校數）、`/api/talent-supply`。
  - `agent/tool_router.py`：`SUPPLY_QUERY`、`DEPARTMENT_QUERY`。
  - `agent/intent_router.py`：用來辨識系所名稱。
  - `engine/talent_supply.py`
  - `benchmark/run_benchmark.py`、`tests/test_etl_quality.py`、`tests/test_official_data_tools.py`
- **替代**：部分替代。
  - 在學、畢業人數 → `tc_udb_dept_annual`。這張只放實際人數，沒有新生數和註冊率。
  - 新生註冊率的原始檔已在 `data/raw/moe_udb_cache/`，但還沒做 ETL。
  - 117 學年推估沒有替代；3 年內的技職畢業生管線可參考 `tc_vocational_dept_annual` 的各年級人數。

### `dept_ucan_industry_mapping.csv`／`ucan_mapping_mart`（已確認：不是模擬，但不可當官方對照）

- **怎麼來的**：`etl/map_ucan_careers.py` 裡**手寫的關鍵字規則**。例如系所名稱含「機械工程」，就對到「製造」職涯和「智慧製造與精密機械」產業。主要／次要對照的權重 1.0／0.5 也是人訂的。
- **為什麼要標記**：
  - `source` 欄寫著 `MOE_UCAN_OFFICIAL_2024`（528 列）或 `GCIS_104_EMPIRICAL_ALIGNMENT`（233 列），但 repo 裡**沒有任何 UCAN 官方檔案或 104 資料**可以佐證這些對照。職涯路徑名稱與代碼（例如 `UC_STEM_PW02 半導體軟硬體整合`）看起來是自訂的。
  - **747 個系所中有 471 個（63%）比對不到任何關鍵字**，被預設歸到「專業商管與金融服務」（`source = MOE_UCAN_DEFAULT_FALLBACK`，533 列），例如歷史學系、教師專業發展研究所。
- **讀取者**：`api/main.py` `/api/talent-supply`；`agent/tool_router.py` `SUPPLY_QUERY`；`engine/talent_supply.py`；`tests/test_etl_quality.py`
- **替代**：尚無替代。需要另外建立有出處的「系所／科別 → 職類 → 產業」對照表（見 `docs/DATA_REQUIREMENTS.md` M3、M4）。

### `demographics_projection.csv`／`demographics_projection`

- **怎麼來的**：109–118 學年的 18 歲人口與全國新生數，直接寫在 `etl/extract_demographics.py` 的 `DEMOGRAPHIC_DATA` 裡。`source` 欄標著 `MOI_ACTUAL`、`MOE_PROJECTION`，但程式沒有讀取任何外部檔案，**數字無法追溯**。
- **讀取者**：
  - `api/main.py` `/api/talent-supply`
  - `agent/tool_router.py` `get_demographics_data`（`DEMOGRAPHIC_QUERY`）
  - `etl/extract_moe_udb.py`：117 學年推估
  - `benchmark/run_benchmark.py`
- **替代**：尚無替代。內政部出生數只從 104 年起，涵蓋不到 3 年後的畢業生；3 年內的技職供給可改看 `tc_vocational_dept_annual` 的各年級在學人數。

## 其他相關檔案

- `data/raw/07_少子化海嘯16年動態模擬推估.csv`：檔名就寫明是模擬推估，全文搜尋找不到任何程式在讀。
- `data/raw/104_taichung_ai_enriched_jobs.csv`、`data/raw/taichung_104_600_jobs_verified.csv`：`companies` 的來源。這兩份是民間平台的職缺資料，其中前者含「代表人／負責人」欄位。
- `README.md` 第五節「七大目標產業定義與動能基準」的數字，都來自 `industry_momentum_mart` 與 `mismatch_signal_mart`，**也是模擬結果**。

## 什麼時候可以刪

每張表都要同時滿足下列條件才刪：

1. 對應的真實表已經接上，相關的 API 端點、助理工具、前端畫面都改讀真實表。
2. 用表名全文搜尋（`*.py`、`*.sql`、`*.html`、`*.js`）找不到任何讀取。
3. `benchmark/` 與 `tests/` 中依賴這張表的測試已改寫或移除。
4. 一起刪除：產生程式、`database/schema.sql` 中的建表語句、`database/mismatch_system.db` 中的表、CSV。
