# 04 真實資料 ETL

舊的 `etl/extract_gcis_batch.py` 與 `etl/extract_demographics.py` 會產生模擬資料，**不要再用**。新的 ETL 放在 `etl/sources/`，一個來源一個模組。

## 怎麼跑

```bash
python -m etl.run_real_etl                    # 下載（已下載的跳過）＋整理＋品質報告
python -m etl.run_real_etl --skip-fetch       # 只用現有原始檔重新整理
python -m etl.run_real_etl --only taiwanjobs  # 只抓今天的就業通職缺快照（建議每天跑）
python -m etl.run_real_etl --only gcis_registry --api-limit 5000   # GCIS API 補查產業別，可分次跑
python -m pytest tests/test_real_etl.py -q    # 驗收：數字對不對得上原始來源
```

每次執行都會更新：

- `data/raw/_manifest.csv`：每個原始檔的下載網址、時間、大小、SHA-256
- `data/processed/_catalog.json`：每張表的來源、粒度、欄位、註記
- `reports/DATA_QUALITY.md`：個資檢查、主鍵重複、缺值、交叉核對

## 產出的表

| 表 | 粒度 | 期間 | 用途 | 來源模組 |
|---|---|---|---|---|
| `tc_company_by_industry_monthly` | 臺中市 × 行業大類 × 月 × 新設／解散／現有 | 2012-06～2026-08 | **預測引擎的主序列**（製造業新設、解散） | `gcis_county_industry` |
| `tc_mfg_company_events_monthly` | 臺中**行政區 × 製造業中類** × 月 × 新設／解散／增資 | 2013-02 起 | 「同業在這區擴張還是退場」 | `gcis_registry` |
| `tc_company_events_coverage_monthly` | 月 × 事件：已判定產業別的比例 | 同上 | 判斷上表每月可信度 | `gcis_registry` |
| `tc_jobmarket_monthly` | 臺中市 × 月：求職、求才、求供倍數 | 2020-01～2026-06（78 個月） | 缺工趨勢、回測 | `taichung_labor_reports` |
| `tc_jobmarket_occupation_q` | 臺中市 × 季 × 職業大類 | 109Q1～115Q2 | 哪類職業最缺 | 同上 |
| `tc_jobmarket_industry_q` | 臺中市 × 季 × 熱門行業求才 | 同上 | 製造業求才量 | 同上 |
| `tc_jobmarket_top_jobs_q` | 臺中市 × 季 × 前 20 職類 | 同上 | 具體職類的求供倍數 | 同上 |
| `tc_factory_district_industry_annual` | 臺中**行政區 × 製造業中類** × 年：工廠家數、從業員工 | 民國 86～113 年（普查年除外） | 「這區這產業有多少工人」（實測值） | `moea_ee520` |
| `tc_factory_survey_city_annual` | 臺中全市 × 中類 × 年 | 2012～2024 | 交叉核對 EE520 | `taichung_opendata` |
| `tc_factory_count_district_monthly` | 臺中行政區 × 工廠產業類別 × 月 | 2024-08～2026-07（18 期，不連續） | 最新的同業家數 | `taichung_opendata` |
| `tc_labor_insurance_annual` | 臺中市 × 行業大類 × 單位類別 × 年（12 月） | 2018～2025 | 製造業總就業人數（控制總數） | `labor_insurance` |
| `tc_vocational_dept_annual` | 臺中高中職 × 群科 × 學年：各年級人數、畢業生 | 103～114 學年 | 未來 3 年技職畢業生管線 | `moe_education` |
| `tc_udb_dept_annual` | 臺中 17 所大專 × 系所 × 學年：在學、畢業 | 105／106～114 學年 | 大專供給 | `moe_education` |
| `tc_taiwanjobs_snapshot` | 快照日 × 職缺 | 2026-10-05 起 | 現在的職缺；每天跑才有歷史 | `taiwanjobs` |

## 處理原則

- **不補值**：來源沒有的月份留 NaN 並標 `missing_at_source`；EE520 未滿 4 家的保密格標 `suppressed_lt4`。
- **異常只標記**：`outlier_candidate` 不刪，建模時再決定。
- **個資不落地**：清冊的代表人、稅籍的營業人名稱與地址、就業通的工作內容全文都在下載當下就刪掉；`write_processed` 會再檢查一次欄位名稱。
- **口徑寫在表上**：例如勞保 `employee_scope`、季報 `scope_period`、就業通 `location_flag`。

## 已知限制

詳見 `reports/DATA_QUALITY.md` 和 `docs/DATA_REQUIREMENTS.md`，重點如下：

- GCIS 2025-08、09 來源缺月；現有家數 2014-11 來源檔損毀。
- 季報只涵蓋市府所轄就業服務據點，2022 年起範圍擴大。
- EE520 是年資料，最新到 113 年；保密格讓員工數少算約 1.6%，小產業影響大。
- **`tc_mfg_company_events_monthly` 的產業別定義與官方統計不同**（方法待決）：本表依財政部稅籍「主要行業代號」判定，2026-08 臺中製造業新設約 20 家，官方統計是 75 家。若改用營業項目判定，「第一項為製造」是 45 家，「任一項為製造」是 102 家。官方的分類規則無法用公開資料重現。
  - 已解散公司不在稅籍裡，需要逐家查 GCIS API，5 年約 4.5 萬家。查完之前，解散事件不列入此表。
  - 全市製造業趨勢請以 `tc_company_by_industry_monthly`（官方統計）為準；行政區 × 中類的同業動向，可改用 `tc_factory_district_industry_annual`（EE520 年度工廠家數與員工變化）和 `tc_factory_count_district_monthly`（最新月快照）。
