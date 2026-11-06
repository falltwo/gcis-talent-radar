# 選址地圖資料更新（Issue #38）

## 已完成範圍

本次處理 Issue #38 的前三個完成條件，不宣稱其餘資料缺口已補齊。

1. #37 已補上 `data/raw/gcis_lists/{setup,dissolved}/2025-08.csv`、`2025-09.csv`；2026-09 月份也已存在。重建後最新 12 個月為 **2025-10～2026-09**，缺月清單為空。2025-08/09 現在不在此最新視窗內，但原始檔仍可供歷史重算。
2. 新增 `etl.build_site_data`，一次重建三個地圖 JSON；既有 `etl.daily_refresh.run()` 預設會在商工整理步驟之後呼叫 `site_data`。Windows 工作排程、cron 和伺服器內建排程都沿用這個入口及既有鎖檔。
3. 新增 `etl.build_district_stats`，定義工廠年度、缺值、職類、地點、快照、去重與上限規則。

## 檔案與來源

| 前端資料 | 產生程式 | 本地輸入 |
| --- | --- | --- |
| `ui/static/district-stats.json` | `etl/build_district_stats.py` | `tc_factory_district_industry_annual.csv`、`tc_taiwanjobs_snapshot.csv`、同日逐郵遞區號原始職缺 CSV |
| `ui/static/gcis-district-activity.json` | `etl/build_gcis_district_activity.py` | `data/raw/gcis_lists/setup`、`dissolved` 的月清冊；不把 daily 子目錄當完整月份 |
| `ui/static/district-talent.json` | `etl/build_district_talent.py` | 各校系所畢業生、校區座標、行政區界線，以及同一份經驗證職缺快照 |

原始來源連結及資料期別寫在 JSON 中。重建是重新計算本地資料，不代表向政府抓到新資料。

目前工廠年度是 **2024**，職缺快照是 **2026-10-05**，畢業生學年度是 **113**。本次沒有重新抓取就業通或教育資料；每日商工更新也不會自動取得它們的新版本。

## 計算規則

### 工廠

取校正統計的最新年度，每區每製造業中類只接受一筆觀察。保密旗標、原始空白或無數值保留 `null`，不補成零。正式產生器也輸出 `factories.employees`；員工數使用 `employees_flag` 獨立判斷，不從工廠家數推估。`factories_flag` 非空亦保留 `null`；重複列、負數及非有限數值會使重建失敗。

舊入口 `scripts/frontend/build_district_stats.py` 已改成呼叫同一個正式產生器；不再從 SQLite 用另一套規則覆寫地圖資料。

### 職缺

- 只取 `tc_taiwanjobs_snapshot.csv` 的最新快照日，不把多天快照累加。
- 工作地點必須明確以「臺中市＋查詢行政區」開頭；排除 `location_flag`，包含「臺中市不限」、其他行政區與外縣市。
- 按職缺 URL 去重；沒有 URL 時採查詢區、職稱、公司、地點、更新日期的組合鍵。
- 雇用人數必須為非負整數。
- 查詢上限依**原始回傳列數**判斷，不能用去重或排除地點後的筆數判斷。預設每區上限 1,000 筆。
- 原始 CSV 必須有職稱、工作地點、職缺 URL 欄位；空白檔、HTML、錯誤表頭或原始列數少於處理後唯一職缺數，都不能證明該區資料完整。
- 區域原始檔不存在時，地圖指標是 `null`，不是 0；達上限的區域在 `capped` 清單內，不參與該職缺指標排名。
- 三區人才報告目前需要所有報告區域具備完整且未達上限的職缺快照；否則重建失敗並保留上一版。此限制避免前端把未知需求讀成 0。

兩個頁面原有口徑不同，本次明確記錄而不悄悄混為一談：

| 用途 | 職務大類 |
| --- | --- |
| 地圖「製造相關職類」 | 技術／維修／操作、品管／製造／環衛 |
| 三區人才報告「技術、製造、工程類」 | 上述兩類，再加工程／研發／生技 |

這是**職類代理指標**，不代表已確認雇主行業屬製造業。刊登筆數與雇用需求人數分開計算，也都不等於缺工人數。本次重建因排除地點不符的 34 列，數字可能與舊 JSON 不同。

### 商工月份

從新設與解散月清冊中找最新月份，再往前取 12 個月。任一類缺檔都列入 `missing_months`，不視為該月 0 家；最新月份只到一類時，也會揭露缺另一類。表頭需有「公司所在地」，地址必須能辨認為臺中 29 區之一；任一類無法解析的列數達 1% 時不發布。

「經營穩定」仍為解散家數／新設家數，沒有公司存量的標準退出率意義。

## 重建與排程

在專案根目錄執行（依 README 安裝依賴）：

```sh
# 不連網，只用本地來源重建三份 JSON
python -m etl.build_site_data

# 單獨重建（排程仍建議用上一個整批入口）
python -m etl.build_district_stats
python -m etl.build_gcis_district_activity
python -m etl.build_district_talent

# 既有每日更新：會呼叫政府來源，最後重建三份 JSON
python -m etl.daily_refresh --skip-tax
```

三種排程的啟用方式沿用 README 及 `etl/scheduler.py`：cron 跑 `scripts/daily_refresh.sh`，Windows 使用 `scripts/register_daily_refresh_task.ps1`，或伺服器設定 `GCIS_DAILY_REFRESH=1`。本次只接入更新步驟，未替使用者安裝作業系統排程或改動環境變數。

每日步驟結果寫入 `data/processed/_daily_refresh.json` 的 `steps.site_data`，包含三個輸出檔名、GCIS 期間／缺月、職缺快照及畢業生學年。上游抓取失敗仍會在其他步驟標失敗；本地重算成功不能把整次抓取失敗改成成功。

## 發布與失敗處理

先完成三份資料的計算及有限 JSON 序列化，再逐檔以暫存檔替換。建置失敗時不動任何原檔；單次檔案替換失敗時會嘗試還原已替換檔案的原始位元組。這不是跨三個檔案的資料庫交易，也不保證磁碟永久故障或程序被強制終止時能完成回復。

## 尚未解決的資料缺口

- 區中心點仍為區內代表點，不是區公所或產業聚落中心，太平區可能落在丘陵。
- 畢業生來源仍只含大專校院，不含高職。
- 沒有接入各區公司存量來計算標準退出率。
- 未新增各區求職者數及期望薪資；這次沒有完成公開來源調查，不宣稱不存在這些資料。
- 畢業生／職缺比只作既有參考訊號，不等於可招到的人數、求職求才比或企業招募成功率。
