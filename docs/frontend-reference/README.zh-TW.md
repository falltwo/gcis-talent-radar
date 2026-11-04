# 校園前端整合參考版（選用）

這是已測試的校園串接參考，不是獨立網站。本後端分支沒有修改正式 ui；要看新資訊欄或鏡頭效果，需由團隊另行整合或套用此 patch。

功能包括正式教育 API、鏡頭飛行／返回、直接匹配與相關科系、公開總機及下方來源。電話為純文字，不顯示查核日期、人數或企業熱門。registry_listed=0 的補充科系另標「名冊未列，招生狀態待查」；不宣稱一定停招，也不保證目前招生。

patch 基準為 main 595f2e2，需先有本分支的後端。它只含九個檔案的差異：五個校園介面檔、四個測試與執行器。沒有完整首頁副本、其他前端模組、vendor 或 node_modules；不修改共用 street-map.js。新增模組的完整內容會出現在 patch 內。

本目錄文字檔統一使用 LF，專案根目錄的 `.gitattributes` 會固定換行，確保 Windows 與 Linux 取出後的校驗值一致。MANIFEST 記錄其他檔案的位元組數與 SHA-256，不包含它自己的校驗值。

如果只收到後端 ZIP，這個目錄可能只有本說明，需先另取同版本的前端參考 ZIP，將其中三個檔案放入此目錄；後端 ZIP 不附前端修改內容。PR 工作目錄則已附好參考 patch 與清單。

## 在另外的整合分支套用

於專案根目錄選擇執行：

```powershell
git apply --check docs/frontend-reference/frontend-reference.patch
git apply docs/frontend-reference/frontend-reference.patch
python -X utf8 -B -m unittest tests.test_campus_frontend tests.test_campus_camera -q
python server.py
```

前端測試需要 Node.js。若從 ZIP 解壓於專案外，將 patch 路徑換成其實際位置。若 main 已更新或介面檔另有修改，先檢查 --check，失敗時手動對照，勿強制覆蓋。

## 分段驗收

1. 選行政區與道路，開啟校園區塊，確認真實校區標記。
2. 輸入「資工系」，切換相關科系，核對兩組結果。
3. 點校區，核對學校、純文字電話、下方來源；不顯示查核日期或人數。
4. 核對補充科系警示與教學校區待核驗提示，兩者不可混為一談。
5. 連續選校區 A、B，返回時回到第一次選校前視角。

地圖與道路定位需要網路及 WebGL。套用前應由團隊決定是否採用；這份檔案不會自動修改正式前端，也不會自動 commit 或推送。
