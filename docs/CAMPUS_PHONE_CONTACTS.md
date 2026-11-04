# 校園地圖學校電話

範圍為目前校園地圖名冊內的 17 所臺中大專校院，涵蓋 22 個校區的學校資訊欄。
不包含臺中所有中小學、補習班或未列入現有大專名冊的單位。

已從教育部「114 學年度全國大專校院及校長名錄」重新下載並核對學校代碼、名稱及「學校總機」欄位。此欄位不取用傳真或教職員個人電話。

來源：[教育部官方名錄 CSV](https://udb.moe.edu.tw/ulist/Resource/download/ulistaddress?extension=csv)。
下載／查核日期：2026-11-03。這是官方名錄內容的線上查核，未實際撥號驗證。
來源檔標示匯出日期為民國 115 年 1 月 8 日；查核日期與來源資料期別分開保留。

## 資料與顯示

- 教育資料庫新增 `education_institution_contacts`，依教育版本與學校 ID 保存。
- 已寫入 17 筆學校總機、國際撥號格式、官方來源 URL、來源 SHA-256、原始檔路徑、資料期別及查核時間。
- 校區查詢、學校清單與校區詳情 API 新增 `school_phone`。
- 前端學校資訊欄以純文字顯示「學校總機」與電話，不提供撥號超連結；下方只保留電話來源連結，不顯示查核日期。後端查核時間仍保留供資料追溯。
- 多校區仍明示這是學校總機，不當作該校區、系所或產學合作專線。例如逢甲中科校區的面板仍標「學校總機」。
- 缺資料時顯示「電話資料待補」，不猜測或以其他學校電話替代。
- 科系名稱、校區、座標及產業資料保留；後續已移除教育人數資料表及舊排行接口，沒有恢復在學人數或企業熱門區塊。

## 更新與驗證

原始官方網頁／CSV 與本機匯入報告沒有附入本分支；官方來源 URL、原始 checksum、資料期別及查核時間仍保留在資料庫。查核時間供資料追溯，不顯示在資訊欄。

如需重新下載官方總機並匯入，使用 Python 3.12 以上的更新環境：

```powershell
python -m pip install -r requirements-education.txt -r requirements-education-geospatial.txt
python -X utf8 -B -m etl.load_education_contacts --download
```

匯入會核對完整學校範圍、建立備份，再以交易寫入。任一學校缺漏、代碼／名稱衝突、電話無法解析或 checksum 不符時，整批失敗並保留原發布資料。電話備份位於已忽略的 `tmp/education-contact-backups/`。

有自己保存的來源 bundle 時，可使用 `--bundle <實際目錄>`；本分支沒有預先附上可直接指定的歷史 raw bundle。可用 `--db` 指定既有教育 DB，缺資料庫時拒絕建立空檔。

隨附資料及總機邏輯可這樣檢查：

```powershell
python -X utf8 -B scripts/verify_campus_delivery.py
python -X utf8 -B -m unittest tests.test_education_contacts -q
```

驗證不依賴未附的原始檔，也不呼叫尚未採用的前端測試。名冊或座標重建新版本後須重新匯入電話，讓聯絡資料綁定新版本。

前端電話純文字、來源連結及隱藏查核日期的示範，位於 [前端參考 patch](frontend-reference/README.zh-TW.md)。本分支沒有直接修改正式前端。
