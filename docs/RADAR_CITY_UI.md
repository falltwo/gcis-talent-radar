# 雷達與真實街區首頁

首頁 `/` 採「訊號聚焦」設計：純黑背景，標題位於置中雷達上方、操作提示位於下方。偵測到的紅點同時出現向內收斂、逐漸消退的四角定位框。GSAP 控制雷達約 3.2 秒淡入，掃描扇形以 5.8 秒／圈持續轉動；掃描角度越過小點方位角時才觸發亮點與光暈，衰減至透明，無獨立隨機閃爍。

地點選單不會自動出現。使用者點擊入口空白處或按一般字元鍵／Enter 才開啟原生 dialog；Tab 保留焦點導覽，快捷鍵、長按重複事件及輸入法組字不會觸發。選單可用關閉按鈕、Esc 或點擊遮罩關閉。背景雷達在選單開啟時繼續轉動。送出地點後淡出至真實 3D 地圖；右上雷達按鈕可返回入口。

提供暫停／播放動態控制；系統偏好減少動態效果時，預設停用掃描與淡入動畫。使用者可自行選擇播放。入口邏輯位於 `ui/static/radar-entrance.js`，樣式位於 `radar-entrance.css`，地圖與資料工作台保留白灰深藍配色。

## 地圖

- MapLibre GL JS 6.16.0（程式與授權檔存於 `ui/static/vendor/maplibre`）。
- OpenFreeMap Positron 樣式的本地中性色修改版，地圖向量磚來自 OpenFreeMap / OpenStreetMap。
- 建物根據地圖中的真實輪廓拉成立體，使用 `render_height`；上游沒有高度時可能使用預設值，本地缺欄位則使用 8 公尺。因此不是測繪級模型，未收錄的建物不會憑空補建。
- 支援拖曳、縮放、右鍵拖曳旋轉，以及旋轉／2D／回到選點按鈕。
- 紅點位於定位服務查得的其中一段道路，不是門牌或整條道路中心。
- 地圖、座標和工廠／職缺統計是不同資料來源。建物不表示製造業工廠，選路不會將區級統計變成路級統計。
- 地圖需要網路及 WebGL。定位失敗時不放紅點；不以其他行政區或相似路名代替。

## 道路索引與定位

`python3 scripts/frontend/build_road_index.py` 從本地 GCIS 2025–2026 公司地址快照整理道路名。這不是完整道路名冊，可能含歷史路名或登記誤植。

`GET /api/map/location?district=大雅區&road=中清路三段` 僅接受選單內道路。由 `engine/street_geocoder.py` 呼叫 Photon，驗證國家、城市、行政區、路名及座標。結果快取於忽略版控的 `data/cache/radar-geocoding`，有效 30 天；不做自動補全或批次查詢。單一服務程序限制呼叫間隔至少 1.1 秒。

`RADAR_GEOCODER_URL` 可更換 Photon 相容服務，預設 `https://photon.komoot.io/api/`。公共示範服務僅適合少量使用，不保證可用性；多人或多程序部署前應改成有容量保證的服務或自架，並統一限流。這版不使用 Nominatim 公共端點。

上游說明：
- https://openfreemap.org/quick_start/
- https://github.com/komoot/photon#demo-server
- https://www.openstreetmap.org/copyright

## 驗證

`python -m pytest tests/test_street_geocoder.py -q` 驗證區域／道路精確匹配、座標有效性、快取、逾時與非法輸入。真實定位另以大雅區中清路三段與西屯區市政路查驗；mock 測試不代表道路完整涵蓋率。

## 分析介面暫時隱藏

目前 `ui/home.html` 的 body 加上 `analysis-paused`，暫時隱藏四項數據摘要、下方詳細分析與相關比較入口。保留雷達入口、3D 地圖、道路定位及問答。既有分析程式及 API 保留；移除 body 的此 class 即可恢復，供後續功能統一整合。

## 企業情境卡

右側位置卡改為企業情境卡（`company-scenario.js`／`company-scenario.css`），預設為明確標示的示範資料：宏辰精密製造、金屬製品製造業、現有員工 80 人、預計增聘 20 人、CNC 技術員與品管人員、目標 6 個月內到職。

候選新廠地址由地點選擇流程更新；座標、定位精度與 OpenStreetMap 連結收在「位置詳情」。點地圖紅點會展開位置詳情。

可編輯公司名稱、產業、員工數、增聘人數、職務及期限；取消不改變已儲存內容。「還原示範」先還原編輯草稿，儲存後才套用。修改後標示「自行填寫」。資料保留於目前分頁的 sessionStorage，不跨分頁同步；目前尚未自動帶入 AI 提問或分析 API，供後續統一整合。這些規劃條件不產生招募成功率。

企業卡目前預設隱藏，點擊地圖紅點才以 MapLibre Popup 錨定在選點上方顯示。右上 × 或 Esc 可關閉，再點紅點可重開；已移除收合控制。切換地點會關閉舊浮窗，編輯內容仍保留。

## 啟動與前端資產

依 README 安裝 Python 依賴後執行 `python server.py`，使用終端機實際顯示的連接埠開啟首頁。已提交鎖定版本的瀏覽器資產，因此一般啟動不需 Node 建置；更新資產時執行 `npm ci` 與 `npm run vendor:frontend`。MapLibre 及地圖來源標示保留在頁面，GSAP 授權告知位於 vendor/gsap/NOTICE.txt。

校園入口操作與展示資料限制見 [CAMPUS_MATCHING_DEMO.md](CAMPUS_MATCHING_DEMO.md)。刊登召募、獵頭 Agent 目前只有準備中入口；本版不包含影片選項、影片 API 或生成流程。
