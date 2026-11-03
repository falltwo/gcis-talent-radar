# 校園地圖後端接口草案

版本：v2，2026-11-03。對照 `codex/campus-backend-pr` 的後端交付版本。

**校園地圖後端已完成，可交給前端串接與團隊驗收；正式部署仍待團隊確認。** 本文件為目前接口與畫面規則的準據。舊計畫書中的在學人數、熱門科系與企業偏好排行已退出目前畫面需求。

## 功能範圍與分工

選擇探索位置 → 搜尋學校／科系 → 點校區 → 前端聚焦 3D 地圖及顯示資訊 → 返回原視角。

| 部分 | 負責內容 | 狀態 |
|---|---|---|
| 教育資料 | 官方學校／系所名冊、校園座標、學校總機與來源 | 已匯入；114 學年度、17 所臺中大專校院、22 個臺中校區、17 筆總機 |
| 後端 | 唯讀搜尋、簡稱與相關科系、詳情、錯誤回應 | 已實作，前綴 `/api/education` |
| 前端 | 飛行／返回、匹配科系、純文字電話、下方來源 | 已有本機實作，等待團隊驗收 |
| 正式環境 | 主機、代理、對外存取及資料更新排程 | 待確認 |

範圍是現有臺中大專校院名冊，不含全臺灣或所有中小學。3D 指地圖視角，沒有新增精細校舍模型。其他 Agent、產業分析與企業比較不屬於此交接。

## 啟動與設定

依專案 [README](../README.md#快速開始) 安裝 Python 環境後執行：

```powershell
python server.py
```

預設 `http://127.0.0.1:8888/`；若埠被占用，以終端印出的網址為準。先前本機預覽使用 8895；前端請使用同源相對路徑，不寫死埠號。

| 設定 | 預設／用途 |
|---|---|
| `EDUCATION_DB_PATH` | 選填，預設 `database/education_directory.sqlite3`；相對路徑以專案根目錄解析 |
| `OPENROUTER_API_KEY` | 校園查詢不需要；其他 AI 功能另行設定 |
| `/docs`、`/openapi.json` | 啟動後查看參數；目前未宣告完整回應 schema，欄位語意以本文件與實際 JSON 為準 |

`server.py` 會載入本機 `.env`。`.env` 與金鑰不得提交。隨附 SQLite 可直接查詢，不必重新下載；缺 DB 時回 503，不會建立空資料庫。

現有頁面與 API 同源。團員另開前端開發伺服器時，建議將 `/api/education` 代理到後端。主程式已有允許任意來源的開發用 CORS；正式部署的來源與憑證政策須另外確認，本次未更動。

## API 一覽

全部使用 `GET`，沒有 request body，成功回 `200 application/json`。沒有校園寫入、保存合作候選或聯絡學校的 API。

| 路徑 | 用途與串接方式 |
|---|---|
| `/api/education/campuses` | **目前資訊欄主要來源**：搜尋、匹配科系、電話、來源 |
| `/api/education/campuses/{campus_id}` | 單一校區詳情；目前開面板直接使用搜尋結果，不另發此請求 |
| `/api/education/coverage` | 資料涵蓋範圍、期別、來源及限制 |
| `/api/education/institutions` | 學校與校區目錄；可能包含這些學校的外縣市校區，不可全部當成臺中結果 |
| `/api/education/departments` | 系所文字查詢與分頁，不等同寬鬆校區搜尋 |

### 1. 校區搜尋

```http
GET /api/education/campuses?latitude=24.15&longitude=120.65&radius_km=30&q=資工系&include_related=true
```

| Query 參數 | 型別 | 必填／預設 | 規則 |
|---|---|---|---|
| `latitude` | number | 必填 | 原點緯度 -90～90，有限數值 |
| `longitude` | number | 必填 | 原點經度 -180～180，有限數值 |
| `radius_km` | number | 15 | 大於 0，單位公里 |
| `q` | string | 空字串 | 最長 80 字；空白查範圍內全部校區 |
| `include_related` | boolean | `false` | `true` 納入人工規則定義的相關科系 |

無分頁；一筆代表一個校區，同校可列多筆。`total` 是校區數，不是學校數。先列 `DIRECT` 再列 `RELATED`，同層依距離、學校名稱、校區 ID 排序。不會自動擴大半徑。

| 回應欄位 | 型別／語意 |
|---|---|
| `release_id` | string，教育資料版本；後續詳情請沿用 |
| `academic_year` | integer，民國學年度，目前 `114`，不是西元 2026 |
| `created_at`、`source_as_of` | string，版本建立時間、來源期別說明 |
| `status` | `OK` 或 `NO_MATCH`；查無結果仍回 200 |
| `total`、`items` | integer、array，命中校區數與資料 |
| `origin`、`radius_km` | `{latitude, longitude}`、number，搜尋範圍 |
| `distance_type` | `GREAT_CIRCLE`，球面直線距離，不是道路或通勤距離 |
| `query_expansion` | `{input: string, department_terms: string[], alias_applied: boolean}` |
| `include_related`、`search_rule_version` | boolean、string；目前規則 `campus-name-rules/2.0` |
| `suggestions` | string[]，空結果時可能提供建議；由使用者點選重查 |
| `verified_campus_count`、`coverage_campus_count` | integer，核驗與收錄數，並非本次命中數 |
| `search_type` | `CAMPUS_AND_DEPARTMENT_NAME_TEXT` |
| `limitations` | string[]，資料及解讀限制 |

`items[]` 的欄位：

| 欄位 | 型別／用途 |
|---|---|
| `campus_id`、`institution_id` | string，後端提供的識別碼；保留前導零，不自行拼接或轉數字 |
| `institution_name`、`name` | string，學校名、校區名 |
| `address`、`city`、`district` | string，名冊地址與行政區；地址未必是所選校區校門地址 |
| `latitude`、`longitude`、`distance_km` | number，核驗代表點與距離；MapLibre 陣列為 `[longitude, latitude]` |
| `coordinate_status` | 本搜尋只列 `VERIFIED_OFFICIAL_GEOMETRY` |
| `coordinate_reference` | object，含 `crs`、`point_type`、`method`、`source_url`、`verified_at` 等依據 |
| `source_url`、`fetched_at`、`website`、`profile_url` | string，名冊來源、取得時間、學校網站與教育部介紹頁 |
| `school_phone` | object，學校總機，見下節 |
| `match_tier`、`match_reason` | `DIRECT`／`RELATED`、string，匹配層級及原因 |
| `match_scope` | `ALL`、`INSTITUTION_NAME`、`CAMPUS_NAME`、`CAMPUS_DEPARTMENT_NAME`、`INSTITUTION_DEPARTMENT_UNLOCATED`、`RELATED_FIELD` |
| `matched_departments` | array，有校區來源關聯且直接匹配的科系；仍需看關聯類型 |
| `unlocated_department_matches` | array，同校直接匹配、尚無校區關聯的科系，不能說就在此校區授課 |
| `related_departments` | array，相關科系；`include_related=false` 時為空 |
| `departments` | array，校區關聯目錄，可能含未匹配科系；**不可整包當作面板符合結果** |
| `institution_department_count`、`unlocated_department_count` | integer，目錄診斷數，非學生人數；目前不顯示 |

科系基本物件含 `department_id`、`institution_id`、`name`、`college`、`website`、`registry_listed`（0／1）、`source_url`。網址可能缺少，前端需允許純文字名稱。

`registry_listed=1` 表示當期系所組織名冊列有此科系；`0` 表示只由同年度補充來源取得名稱，當期組織名冊未列出。`0` 不代表確定停招，也不能宣稱目前仍招生。前端應保留名稱並顯示「名冊未列，招生狀態待查」，此提示與教學校區是否核驗是兩回事。

有校區關聯時另帶 `relation_type`、`relation_label`、`relation_source_url`：

| `relation_type` | 意義 |
|---|---|
| `SINGLE_OFFICIAL_CAMPUS` | 單一官方校區推定，未逐系核驗授課地點 |
| `DEPARTMENT_CONTACT_ADDRESS` | 系所聯絡地址，不等於教學校區證明 |
| `VERIFIED_TEACHING` | 已核驗教學校區依據 |

相關科系另有 `location_status`：`RELATED_TO_CAMPUS` 表示有上述關聯，仍須看 `relation_type`；`TEACHING_LOCATION_UNVERIFIED` 表示授課校區待核驗。匹配到校名也不代表全校每個科系都符合搜尋。

### 2. 學校電話與來源

以下為目前資料的實際物件：

```json
{
  "status": "AVAILABLE",
  "label": "學校總機",
  "kind": "INSTITUTION_SWITCHBOARD",
  "display": "04-2218-3199",
  "tel_uri": "tel:+886422183199",
  "source_url": "https://udb.moe.edu.tw/ulist/Resource/download/ulistaddress?extension=csv",
  "source_sha256": "c06b7d2e4efc740e6264133c7d72a3fe3db19c6b0a90a99dee229510b8371fe4",
  "source_period": "114學年度全國大專校院及校長名錄(含學校本部地址)",
  "checked_at": "2026-11-03T16:59:00+08:00"
}
```

前端純文字顯示 `display`，**不建立電話超連結**；`tel_uri` 僅相容保留。面板下方只顯示電話來源連結，不顯示查核日期。`checked_at` 仍由後端保存供來源追溯；它不是官方資料更新日，亦未實際撥號驗證。

缺資料時 `status=UNAVAILABLE`，`display`、`tel_uri`、`source_url`、`checked_at` 為 `null`，其他欄位可能省略；顯示「電話資料待補」。總機屬於學校，不是校區、科系或產學合作專線。

### 3. 校區詳情

```http
GET /api/education/campuses/0039%3A91828657de9d6b82?release_id=edu-geo-7e72d5d13c8731c9acf4d132
```

必填 path `campus_id`（string）；選填 query `release_id`（string），省略讀目前版本。回 `{release_id, academic_year, campus}`。

`campus` 含識別碼、學校／校區名、地址、經緯度、座標依據、網站、`school_phone`、`departments`。沒有搜尋上下文、`distance_km`、匹配科系陣列或 `match_tier`，不能單靠此接口重建符合搜尋的科系。

校區詳情不包含統計或排行區塊；舊統計路由已移除，呼叫會回 404。

### 4. 名冊接口

| 接口 | 參數與回應摘要 |
|---|---|
| `coverage` | 無參數；回版本、範圍摘要、限制及 `sources[]`（URL、取得時間、SHA-256） |
| `institutions` | 無參數；回 `{release_id, academic_year, total, scope, items}`；學校含總機與校區目錄 |
| `departments` | `q=''`（最長 80 字）、`institution_id`、`district`、`release_id` 選填；`page=1`（至少 1）、`page_size=50`（1～100）；回版本、年度、`total`、`items`、分頁、`status`、`limitations`、`search_type` |

`departments` 是校名／系名子字串查詢，**沒有簡稱與相關領域擴展**。`district` 只接受有效臺中行政區，且只列 `VERIFIED_TEACHING` 科系；空結果可回 `NO_VERIFIED_LOCATION`，不代表該區沒有學校。無行政區條件則回 `NO_MATCH`。不回傳 `programs` 或人數欄位。

## 前端範例與畫面規則

同源請求範例；重新搜尋時，呼叫端應取消舊請求，並用請求序號忽略過期回應。現有控制器已有此處理。

```js
async function searchCampuses({ latitude, longitude, radiusKm = 15,
  query = '', includeRelated = false, signal }) {
  const params = new URLSearchParams({ latitude, longitude,
    radius_km: radiusKm, q: query, include_related: includeRelated });
  const response = await fetch(`/api/education/campuses?${params}`,
    { signal, cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(response.status === 503 ? '校園資料暫時無法讀取，請重試'
      : response.status === 422 ? '請確認查詢位置、名稱與半徑'
      : `查詢失敗（HTTP ${response.status}）`);
  }
  return data; // items=[] 是有效空結果，顯示建議與調整條件
}

function departmentsForPanel(item) {
  const direct = new Map([
    ...(item.matched_departments || []),
    ...(item.unlocated_department_matches || [])
  ].map(d => [d.department_id, d]));
  const related = new Map((item.related_departments || [])
    .filter(d => !direct.has(d.department_id))
    .map(d => [d.department_id, d]));
  return { direct: [...direct.values()], related: [...related.values()] };
}
```

1. 資工／資工系由後端對應資訊工程；相關科系由 `include_related` 控制。規則為人工維護的名稱／領域關聯，不是 AI 分數或官方排名。
2. 面板只列直接匹配與相關科系，依 ID 去重。未匹配科系時，提示先搜尋科系，不列全校名單。不顯示人數、熱門或企業偏好排行。
3. 選校、飛行、返回由前端控制；後端提供座標，不提供相機狀態。連續選 A、B 再返回，回到第一次選校前視角。
4. 電話純文字，來源集中下方。缺網址保留文字，缺電話顯示待補，不填假資料。
5. 搜尋版本改變時清除舊合作候選，詳情沿用搜尋的 `release_id`。合作候選目前只留在當頁記憶體，重整清空，也不會聯絡學校。

實作參考：[後端路由](../api/education.py)、[前端整合參考說明](frontend-reference/README.zh-TW.md)。前端修改以獨立 patch 提供，不要求正式畫面直接採用。本後端是 GET／JSON 查詢，沒有背景任務或 SSE，不產生模型 token 費用。

## 空結果、錯誤與版本

| HTTP／內容 | 條件 | 前端處理 |
|---|---|---|
| 200，`OK` | 有結果 | 顯示結果與匹配原因 |
| 200，`NO_MATCH`、`items=[]` | 條件內查不到 | 顯示空結果及建議；不當作系統故障 |
| 200，`NO_VERIFIED_LOCATION` | 系所行政區篩選缺已核驗地點 | 提示授課校區資料不足 |
| 404，`{"detail":"找不到此版本的校區"}` | 指定校區不存在 | 重新搜尋；已移除的舊統計路由亦回 404 |
| 422，`detail` 是 string 或錯誤 array | 必填缺漏、型別／範圍錯誤 | 顯示輸入錯誤，不一律將 `detail` 當字串 |
| 503，`detail` 是 string | DB 缺失／不可讀、無發布版本或指定版本不存在 | 保留條件，提示重試／重新搜尋；不補假資料 |

目前未知 `release_id` 回 **503**，不是 404。只有詳情與系所名冊接口接受版本參數；校區搜尋、學校目錄讀目前版本。

## 來源、更新與限制

- 學校／科系使用教育部官方名錄，座標有獨立幾何來源與查核依據。URL、資料期別、取得時間、checksum 分開保存，不把下載日當資料年度。
- 總機取官方學校總機欄，不取傳真或個人電話。匯入核對完整 17 校，備份後交易寫入；失敗保留原發布內容。詳見 [電話資料說明](CAMPUS_PHONE_CONTACTS.md)。
- 教育部學生統計來源只用於補充科系名稱及核對年度，不保存人數、學制統計或排行；原始來源不附交付包。
- 校園 API 唯讀存取獨立 `database/education_directory.sqlite3`，不讀寫產業 DB。更新由 ETL 執行，不是每次查詢即時爬學校網站。
- 重建教育版本後須重跑電話匯入，綁定新版本。勿改寫原始檔換行，以免破壞已保存 checksum。
- 代表點不是校門，直線距離不是通勤距離，同校系所不等於確認在選中校區授課。沒有職務媒合分數、就業率或企業排行。
- 圖磚／地圖樣式與道路定位需網路，3D 需 WebGL；校園查詢不需外部模型或新金鑰。
- 目前校園端點未實作登入或限流，對外存取、代理與更新排程仍須團隊確認，尚未完成正式環境驗收。

## 驗證與交付

```powershell
python -X utf8 -B scripts/verify_campus_delivery.py
python -X utf8 -B -m unittest tests.test_campus_map_api tests.test_campus_details tests.test_education_contacts tests.test_education_directory tests.test_campus_coordinates -q
```

後端專項共 32 項，需先以 Python 3.12 以上安裝兩份教育 requirements。交付檢查為唯讀，驗證 SQLite 完整性／外鍵、17 校／22 校區／17 筆總機及基本接口；不重新驗證未附的原始官方檔案。前端參考版的 10 項測試須另套用參考 patch 後執行，不能直接在純後端分支呼叫尚未存在的前端測試模組。

操作步驟見 [後端啟動與驗證](CAMPUS_BACKEND_SETUP.md)；本次提交前檢查摘要見 [驗證摘要](CAMPUS_PR_VALIDATION.md)。

舊統計接口、資料表及企業證據檔已移除；科系名稱與來源保留。後端分支保留 main 原前端，正式畫面仍需逐項串接驗收。參考文件的要素與採用理由另見 [交接說明](CAMPUS_API_HANDOFF.md) 或 [單頁閱讀版](CAMPUS_API_HANDOFF.html)。
