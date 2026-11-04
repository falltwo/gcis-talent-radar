# 校園功能契約 v4

目前接口與畫面規則統一以 [校園地圖後端接口草案](CAMPUS_API.md) 為準（2026-11-03）。後端 PR 分支 `codex/campus-backend-pr`；基準 main `595f2e2`。`.env` 與金鑰不納入提交。

- 鏡頭狀態：overview → flying → detail → overview。首次進入保存總覽相機；連點不覆蓋；返回恢復；換道路取消且丟棄舊快照。詳情可在飛行被中斷後閱讀。
- 搜尋 API 保留原參數和預設直接命中，新增 `include_related=false`。新前端明示勾選相關領域。回應新增 `match_tier`、`match_reason`、`related_departments`、`search_rule_version`、`suggestions`，不改距離或原校區歸屬意義。
- 詳情 API：`GET /api/education/campuses/{campus_id}?release_id=...`，固定教育版本，包含校區概況與已核驗／未核驗系所關聯。無此實體 404、無資料庫 503、輸入錯誤 422。
- 現行面板直接使用搜尋結果，只列符合與相關科系，不顯示在學人數、全校排行或企業偏好。
- 舊 `department-insights` API、詳情 `insights`、系所 `programs` 已移除；教育資料庫不再存人數表，企業排行證據檔已刪除。
- 學校總機為純文字，不提供電話超連結；面板下方只顯示來源連結，不顯示查核日期。
- 各端點唯讀，不改原產業或教育 SQLite；來源盤點及展示參考使用獨立版本化 JSON。
- 無新外部 API 金鑰需求，不使用模型生成排行。`.env` 與其他區塊不納入修改。

原 v2 在學規模及排行規劃已由使用者後續需求與本版取代。補充科系需顯示「名冊未列，招生狀態待查」。
