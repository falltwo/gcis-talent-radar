# 校園後端啟動與驗證

本分支已把教育路由註冊進主程式，並補上 CI 依賴設定，不需要再套用後端註冊 patch。本分支包含可供團隊審查的程式、資料及接口文件。

如果是從候選 ZIP 交付，請先依包內 README 套用路由註冊、CI 及備份忽略三個 patch；本說明其餘步驟皆在套用後執行。PR 分支已直接包含這些實際修改。

## 啟動

先依專案 README 安裝原有後端環境，再於專案根目錄執行：

```powershell
python server.py
```

預設網址為 `http://127.0.0.1:8888/`；被占用時以終端印出的網址為準。開啟 `/docs` 可測試五個教育接口。校園資料查詢不需要 OpenRouter 金鑰，使用隨附教育 SQLite 即可，不需先跑 ETL。

**本分支沒有修改正式 `ui/`。** 原版校園畫面尚未呼叫新教育 API，因此後端正常不等於首頁已顯示新學校資訊。團隊可依 [接口草案](CAMPUS_API.md) 串接，或選擇另行套用 [前端參考 patch](frontend-reference/README.zh-TW.md)。

## 資料驗證與後端測試

不需額外地理套件即可檢查交付資料：

```powershell
python -X utf8 -B scripts/verify_campus_delivery.py
```

此工具檢查交付的當前資料版本、完整性、外鍵、17 校／22 校區／17 筆總機、簡稱及基本查詢，並確認讀取前後 hash 相同。原始來源沒有隨交付附上，這裡不宣稱重新驗證原始檔。

更新資料或跑全部教育測試需要 **Python 3.12 以上**：

```powershell
python -m pip install -r requirements-education.txt -r requirements-education-geospatial.txt
python -X utf8 -B -m unittest tests.test_campus_map_api tests.test_campus_details tests.test_education_contacts tests.test_education_directory tests.test_campus_coordinates -q
python -m pytest tests -q
```

五支後端測試使用隔離資料，不改寫正式教育 DB。前端參考版的測試不在正式後端測試樹中，只有套用前端 patch 後才可執行。

## 資料更新與提交範圍

名冊、座標、總機各有獨立 ETL；操作電話更新見 [電話資料說明](CAMPUS_PHONE_CONTACTS.md)。名冊／座標更新前產生的 `data/backups/education/` 已列入 `.gitignore`；電話備份位於已忽略的 `tmp/education-contact-backups/`。

資料庫只保存教育目錄、科系名稱、座標、公開總機與來源，不含舊人數表或企業排名。`.env`、備份、原始網頁、日誌、原產業 DB 及本機工具不納入提交。

正式前端要分段驗收校區搜尋、科系匹配、資訊欄、鏡頭互動；參考 patch 只作選用整合版本。
