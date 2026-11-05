# 後端資料庫盤點

盤點日期：2026-11-05。只讀取結構與筆數，未匯出憑證或個人資料。

## database/mismatch_system.db

產業、官方職缺、公司與人才供需指標；部分舊 mart 為模擬／推估資料，不能當市場事實。

| 資料表 | 筆數 |
|---|---:|
| `companies` | 821 |
| `demographics_projection` | 10 |
| `department_indicators_mart` | 3700 |
| `gcis_new_company_monthly` | 3591 |
| `industry_dynamics_mart` | 1015 |
| `industry_mapping_rules` | 45 |
| `industry_momentum_mart` | 7 |
| `labor_insurance_baseline` | 735 |
| `mismatch_signal_mart` | 7 |
| `official_job_fetch_audit` | 29 |
| `official_job_vacancies` | 2822 |
| `talent_supply_mart` | 7 |
| `ucan_mapping_mart` | 1294 |

## database/education_directory.sqlite3

學校、校區、科系、職涯對照、聯絡資訊、來源及審核證據。

| 資料表 | 筆數 |
|---|---:|
| `education_active_release` | 1 |
| `education_campuses` | 230 |
| `education_career_aliases` | 5 |
| `education_career_supplements` | 38 |
| `education_coordinate_evidence` | 22 |
| `education_department_campuses` | 295 |
| `education_departments` | 609 |
| `education_institution_contacts` | 17 |
| `education_institutions` | 149 |
| `education_releases` | 1 |
| `education_review_tasks` | 384 |
| `education_sources` | 178 |

## database/recruitment.sqlite3

企業招募：公司、使用者、工作階段、對話、薪資／職缺範本、批次草稿、已刊登職缺及稽核。

| 資料表 | 筆數 |
|---|---:|
| `access_tokens` | 3 |
| `audit_logs` | 3 |
| `chat_logs` | 0 |
| `companies` | 1 |
| `job_postings` | 0 |
| `job_templates` | 0 |
| `recruitment_batch_items` | 0 |
| `recruitment_batches` | 0 |
| `salary_templates` | 0 |
| `users` | 1 |

## data/recruitment-history/templates.sqlite

公開職業研究的歷史範本快取；保留30日、最多200筆，不保存企業HR原文。

| 資料表 | 筆數 |
|---|---:|
| `job_template_history` | 2 |

## 按功能建立的資料庫

`database/comparison_reports.sqlite3`：企業多區比較報告快照、來源解析、冪等請求與稽核；本機目前尚未建立。由 `COMPARISON_REPORT_DB` 可改路徑。

舊招募服務使用 `database/mismatch_system.db`，需要通過其獨立驗證後才執行 `database/recruitment.sql`，新增 `recruitment_*` 表；目前主資料庫尚未出現這些表，與新招募 MVP 的 `recruitment.sqlite3` 是兩套不同實作。

測試資料庫位於 `.test-data/` 或 `output/`，屬測試產物，未列為產品正式資料來源。

## 路徑設定

- 主資料庫：`config.DB_PATH`。
- 校園：`EDUCATION_DB_PATH`。
- 招募MVP：`RECRUITMENT_DATABASE_URL`；預設SQLite，也支援設定PostgreSQL。
- 職業研究快取：`RECRUITMENT_TEMPLATE_HISTORY_DB`。

目前沒有可直接回答「前端工程師市場平均薪資」的專門統計資料表；`salary_templates` 是企業已儲存薪資參考，`labor_insurance_baseline` 是投保薪資基準，均不能冒充該職稱的市場平均實領薪資。
