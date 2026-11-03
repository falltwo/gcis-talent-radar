# PR #22 前端串接 API 規格草稿

版本：0.1-draft · 日期：2026-11-03 · 適用PR：[HR招募建議與Computer Use模擬刊登 #22](https://github.com/falltwo/gcis-talent-radar/pull/22)。

本稿供前端接「輸入需求 → 產生建議 → HR核准 → Computer Use填表 → 再次確認 → 模擬刊登」。內容依PR後端版本`2ee42eee64d25458929dfdb9914f052377dbb300`及隔離展示實測整理；本次只補文件，不新增接口。

- [流程圖與例外處理](RECRUITMENT_FLOW.md)
- [35類常見職缺及別名](COMMON_JOB_TEMPLATES.md)
- [OpenAPI JSON](api/pr22-openapi.json)：從實作擷取的路由、請求模型及驗證條件。
- [實測JSON範例](api/pr22-examples.json)：包含初始化、產生建議、核准、取消與手動刊登成功／失敗；均為虛構隔離資料，沒有啟動模型或送到正式平台。

本次匯出52個HTTP操作、22個請求／驗證模型，並驗證16組隔離請求與回應。以下主文聚焦新工作台，企業後端與固定展示列於第10節。

**草稿限制：目前不少接口未宣告`response_model`，因此OpenAPI的成功回應schema仍是空物件。請求模型可直接對照OpenAPI；回應型別先以本稿與實測範例為準，待雙方確認後再正式版本化。**

## 1. 環境與連線約定

| 項目 | 約定 |
|---|---|
| 本機展示根網址 | `http://127.0.0.1:8890`，連接埠依啟動設定調整 |
| 主流程前綴 | `/api/mock104` |
| 傳輸格式 | JSON；有body時送`Content-Type: application/json` |
| 身分與工作 | `POST /start`建立`mock104_demo` Cookie；瀏覽器自動帶回 |
| Cookie | HttpOnly、SameSite=Strict、Path=/api/mock104；HTTPS時Secure |
| 前端fetch | 同來源使用`credentials: "same-origin"`及`cache: "no-store"` |
| 另開前端開發埠 | 建議使用開發伺服器proxy，讓瀏覽器仍以同來源呼叫；不可假定只改成`credentials: "include"`就已支援跨來源寫入 |
| 寫入來源 | 傳入Origin時，必須與後端的scheme及host:port一致，否則403 |
| 展示資料 | 隔離暫存SQLite；約20分鐘固定期限，服務重啟後消失；重複start不會延長期限 |
| 資源上限 | 最多32個展示工作階段；每個工作階段最多50筆職缺 |
| 模擬標示 | 全程不做正式104／1111刊登；有`mode`、`sent_to_platform`或`notice`的回應應保留其模擬意義 |

前端不需也不可持有OpenRouter金鑰。一般範本不呼叫模型；網路研究與獨立瀏覽器由後端設定啟用。Computer Use入口只接受本機請求，且Chrome開在後端所在的電腦，尚非多人遠端瀏覽器服務。

使用開發proxy時，需讓轉送後的Host與Origin仍符合來源檢查。browser/start會用請求的base URL開啟`/mock104`，因此同來源代理還要能提供`/mock104`及其`/static/*`資源，不能只代理API後把網站路徑交給前端SPA。請保留來源檢查；實際proxy設定需依開發環境確認。

## 2. 前端最小呼叫順序

| 順序 | 何時呼叫 | 方法與路徑 | 前端接下來做什麼 |
|---|---|---|---|
| 1 | 第一次產生建議前 | `POST /api/mock104/start` | 讓瀏覽器取得Cookie |
| 2 | 已有職稱 | `GET /api/mock104/agent/strategy?role=測試員` | 顯示套範本或網路搜尋、設定本次等待時間 |
| 3 | 按「產生招募建議」 | `POST /api/mock104/agent/prepare` | 用`job`填入可編輯審核表，顯示來源及建議標籤 |
| 4 | HR確認或修改後 | `POST /api/mock104/agent/approve` | 取得`run_id`；以回傳`job`作為核准準據 |
| 5 | 核准成功後 | `POST /api/mock104/agent/browser/start` | 開啟獨立Chrome；開始輪詢 |
| 6 | 工作進行中 | `GET /api/mock104/agent/run` | 約每1.5秒查詢最新狀態及截圖 |
| 7 | `AWAITING_CONFIRMATION`且HR確認 | `POST /api/mock104/agent/browser/resume` | Agent繼續操作一般網站，維持輪詢 |
| 8 | HR按停止 | `POST /api/mock104/agent/cancel` | 顯示取消狀態；實際瀏覽器在目前決策返回後停止 |
| 選用 | 恢復網站職缺列表 | `GET /api/mock104/state` | 有效session回傳列表；無有效session回204 |

主流程採**輪詢**，沒有SSE或WebSocket。`run_id`不放在`GET /agent/run`網址；該接口取目前Cookie工作階段的最新工作。

## 3. 初始化與路徑判斷

### POST `/api/mock104/start`

請求body：`{}`。成功200，設定Cookie並回傳網站快照；若已有有效session則回傳現有資料，不清空職缺。

```json
{
  "jobs": [],
  "mode": "SIMULATION",
  "sent_to_platform": false,
  "notice": "獨立模擬求才平台，非104官方網站，不會刊登至104。"
}
```

`GET /api/mock104/state`成功也是這個結構；**204沒有JSON body**，前端不可直接呼叫`response.json()`。

### GET `/api/mock104/agent/strategy?role={職稱}`

`role`長度1–120，須URL編碼。此接口不消耗模型次數，不會搜尋網路，也不代表模型金鑰或額度已可用。

```json
{
  "source": "OCCUPATIONAL_TEMPLATE",
  "template_name": "測試員",
  "max_wait_seconds": 15
}
```

未收錄時回`source: "LIVE_WEB_RESEARCH"`、`template_name: null`、`max_wait_seconds: 60`。前端顯示對應訊息；後續prepare仍由後端自行判斷，不接受前端強制假稱命中範本。

## 4. 產生待確認招募建議

### POST `/api/mock104/agent/prepare`

新前端使用`mode: "AUTO"`。此請求同步等待結果，尚未建立職缺或啟動瀏覽器。

```json
{
  "mode": "AUTO",
  "company_name": "",
  "company_intro": "",
  "district": "大里區",
  "role": "測試員",
  "needs": "招募三人 月薪面議"
}
```

| 欄位 | 型別／必填 | 限制 |
|---|---|---|
| `role` | string，必填 | 1–120字 |
| `district` | string，必填 | 1–80字 |
| `needs` | string，必填 | 5–2500字 |
| `company_name` | string，選填 | 預設空字串，最多120字 |
| `company_intro` | string，選填 | 預設空字串，最多1000字 |
| `mode` | enum，選填 | 預設AUTO；MODEL、SAMPLE為既有相容模式，詳見附錄 |

成功200回傳以下欄位；完整值見`pr22-examples.json`的`prepare`。

| 回應欄位 | 型別 | 前端用途 |
|---|---|---|
| `job` | JobForm物件 | 填入HR可修改的表單，見第5節 |
| `source` | `OCCUPATIONAL_TEMPLATE`或`LIVE_WEB_RESEARCH` | 標示建議來源 |
| `template_name` | string或null | 命中的範本名稱，網路研究為null |
| `sources` | Source陣列 | 可點擊來源，並區分預存參考與本次研究 |
| `field_provenance` | 欄位名對`HR_INPUT`／`SUGGESTED`的對照 | SUGGESTED顯示「建議／待確認」 |
| `review_notes` | string[] | 顯示職務方向、未確認條件等提醒 |
| `requires_hr_review` | true | 必須由HR核准 |
| `missing_fields` | string[] | AUTO目前回空陣列；不表示建議已成為公司事實 |
| `notice` | string | 顯示整理結果的適用範圍 |

Source型別：`{title: string, url: string, retrieved_at: string | null, status?: "CURATED_REFERENCE"}`。

範本來源有`status: "CURATED_REFERENCE"`、`retrieved_at: null`，不是本次即時抓取。網路來源有UTC查詢時間，目前不保證有status欄位。連結以文字建立，另開分頁時加`rel="noopener noreferrer"`；不要把來源或模型內容直接插成HTML。

常見範本不需模型設定。未知職位的研究最多每session 3次、服務每分鐘10次，失敗嘗試也可能消耗次數。搜尋逾時、格式錯誤或沒有可追溯來源時回錯誤，不會換成假搜尋結果。

## 5. HR核准時提交的 JobForm

只提交`job`中的資料與HR修改值，不要把`source`、`field_provenance`等回應metadata放進job；不接受多餘欄位。

| 欄位 | 型別 | API規則／預設 |
|---|---|---|
| `title` | string | 必填，1–120字 |
| `company_name` | string | 必填，1–120字；未提供的示範名稱須顯示待HR確認 |
| `district` | string | 必填，1–80字 |
| `shift` | string | 必填，1–80字 |
| `headcount` | integer | 必填，1–10000 |
| `salary_mode` | `RANGE`／`NEGOTIABLE` | 預設RANGE，建議前端每次明傳 |
| `salary_min` | integer或null | 範圍模式必填，1–10000000 |
| `salary_max` | integer或null | 範圍模式必填，1–10000000，且不得小於min |
| `employment_type` | `全職`／`兼職` | 預設全職 |
| `schedule_system` | `固定班制`／`排班制`／`輪班制` | 預設固定班制 |
| `work_hours` | string | 最多120字，預設空；**Agent核准時不可空白** |
| `min_experience_months` | integer | 0–600，預設0，單位為月 |
| `required_skills` | string[] | 最多30項，預設[]；每項去空白後1–80字 |
| `trainable_skills` | string[] | 同上 |
| `description` | string | 最多5000字，預設空；**Agent核准與送審時至少10字** |
| `company_intro` | string | 最多1000字，預設空 |

文字會去除頭尾空白；技能會去空白、去重並轉為casefold形式。以approve回傳的job作為最後核准版本，不要用原始輸入自行比較。

薪資面議必須送`salary_mode: "NEGOTIABLE"`且`salary_min: null`、`salary_max: null`；不可送0、空字串或猜測區間。範圍模式兩個數字都要填。

為讓目前模擬網站可由Computer Use操作，前端請採用該網站既有選項：

- 地區：大雅區、西屯區、大里區、太平區、潭子區、神岡區、烏日區、南屯區、豐原區。
- 班別：日班、晚班、大夜班、輪班。API的shift本身是字串，但任意字串不保證能填入網站下拉選單。
- 工作經驗：網站選項為0、12、24、36、60月。API接受0–600，不代表目前Computer Use網站可選到任意月份。

## 6. 核准、啟動與操作進度

### POST `/api/mock104/agent/approve`

下例在async事件處理器或ES module中執行。

```javascript
const approved = await api('/agent/approve', {
  job: editedJob,                 // 完整JobForm，HR已檢查或修改
  hr_confirmed: true,
  confirm_before_publish: true,   // 預設true；false代表填表核對完成後繼續模擬刊登
  scenario: 'SUCCESS'
});
const runId = approved.run_id;
```

`hr_confirmed`只接受true。成功200回傳RunSnapshot，初始phase為READY；此時瀏覽器尚未啟動。`scenario`雖接受SUCCESS／FAILURE，但目前HR工作台只使用SUCCESS，Computer Use未保證會自行選取失敗情境；失敗展示請使用第8節的手動網站流程。

`typing_speed`是相容欄位，預設NORMAL，可接受FAST；目前外部Computer Use未使用此值控制速度，新前端不需提供。

### POST `/api/mock104/agent/browser/start`

body：`{"run_id":"核准回傳的UUID"}`。只接受目前session的READY工作。成功200：

```json
{
  "started": true,
  "driver": "COMPUTER_USE",
  "notice": "會另開獨立Chrome，以截圖及滑鼠鍵盤操作一般網頁。"
}
```

此回應只表示已派出瀏覽器工作，不代表填表成功。之後透過GET run判斷進度；缺Chrome等非同步錯誤可能在run的FAILED及message出現。

同時最多2個外部瀏覽器；同一session只能有一個仍在執行的瀏覽器。完成後Chrome可保留最多5分鐘，若新啟動遇到409，先關閉上一個Chrome並等候回收，不要不斷重送start。

### GET `/api/mock104/agent/run`

成功200回最新RunSnapshot。以下為AUTO主流程的前端型別草稿：

```typescript
type RunPhase = 'READY' | 'COMPUTER_RUNNING' | 'AWAITING_CONFIRMATION'
  | 'COMPUTER_PUBLISHING' | 'PUBLISHED' | 'FAILED' | 'CANCELLED';

interface RunSnapshot {
  run_id: string;
  job: JobForm;                 // 第5節
  job_id: string | null;         // 已核對成功的網站職缺ID，與run_id不同
  phase: RunPhase;
  confirm_before_publish: boolean;
  scenario: 'SUCCESS' | 'FAILURE';
  typing_speed: 'NORMAL' | 'FAST';
  mode: 'SIMULATION';
  sent_to_platform: false;
  driver: 'COMPUTER_USE';
  screenshot: string | null;    // 純Base64 JPEG，不含data:前綴
  message?: string;             // READY可能沒有
  step?: number;                // 從1開始的模型畫面決策回合，並非百分比
  steps: unknown[];             // 相容欄位，目前不是逐步事件紀錄
}
```

這是現行資料形狀的文件型別，不代表後端已用response_model強制此型別。舊版claim／filled流程可能出現其他phase，新前端不要混用。

| phase | 顯示建議 | 可以執行 |
|---|---|---|
| READY | 需求已核准，待開啟瀏覽器 | browser/start、cancel |
| COMPUTER_RUNNING | 正在填表／修正／預覽 | 繼續輪詢、cancel |
| AWAITING_CONFIRMATION | 請HR確認網站上實際內容 | browser/resume、cancel；也可在Chrome手動送出 |
| COMPUTER_PUBLISHING | 正在模擬送審與刊登 | 繼續輪詢、cancel |
| PUBLISHED | 模擬刊登完成 | 停止輪詢，查state顯示職缺結果 |
| FAILED | 操作失敗，顯示message | 停止自動輪詢；可cancel清理仍開啟的工作 |
| CANCELLED | 已要求停止操作 | 停止輪詢；不要宣稱已撤銷既有職缺 |

圖片顯示方式：`img.src = 'data:image/jpeg;base64,' + run.screenshot`。null時保留等待畫面。截圖是最近一次決策畫面，不是連續直播，也沒有保證每秒更新。message使用textContent顯示。

建議1.5秒一次、上一個請求完成後再排下一次，避免慢連線下重疊輪詢。比對回傳run_id與前端正在展示的run_id；同Cookie多分頁共用最新工作，若ID不同應停止舊輪詢並提示重新取得狀態。

### POST `/api/mock104/agent/browser/resume`

body：`{"run_id":"目前run_id"}`。只在AWAITING_CONFIRMATION且HR已確認時呼叫。成功200回RunSnapshot，phase改為COMPUTER_PUBLISHING；仍需繼續輪詢。前端不應自行呼叫網站submit來假裝Agent完成操作。

### POST `/api/mock104/agent/cancel`

body同上。成功200回目前RunSnapshot。未完成工作改為CANCELLED；已PUBLISHED或CANCELLED時回原狀態。

取消不是交易回滾：已存草稿或已完成的模擬刊登仍可能存在。取消檢查在目前模型決策返回後、下一個滑鼠鍵盤動作前；不保證立刻關Chrome。已PUBLISHED時cancel不會關閉保留中的瀏覽器，可自行關閉或等待到期。

## 7. 通用前端呼叫與輪詢範例

以下為可改寫成專案API層的範例，`api()`路徑相對於`/api/mock104`。Abort只停止前端等待，不表示後端工作已取消。

```javascript
async function api(path, body, method = 'POST', timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch('/api/mock104' + path, {
      method,
      credentials: 'same-origin',
      cache: 'no-store',
      signal: controller.signal,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    if (response.status === 204) return null;
    const data = await response.json();
    if (!response.ok) {
      const message = typeof data.detail === 'string'
        ? data.detail
        : '欄位格式有誤，請檢查detail中的欄位驗證資訊。';
      const error = new Error(message);
      error.status = response.status;
      error.detail = data.detail;
      throw error;
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

async function prepareForReview(input) {
  await api('/start', {});
  const strategy = await api('/agent/strategy?role=' + encodeURIComponent(input.role),
    undefined, 'GET');
  // 先顯示strategy.source及template_name，再等待結果。
  return api('/agent/prepare', { ...input, mode: 'AUTO' },
    'POST', strategy.max_wait_seconds * 1000);
}

function watchRun(runId, render, showError) {
  const terminal = new Set(['PUBLISHED', 'FAILED', 'CANCELLED']);
  let stopped = false, timer;
  function stop() { stopped = true; clearTimeout(timer); }
  async function tick() {
    try {
      const run = await api('/agent/run', undefined, 'GET');
      if (stopped) return;
      if (run.run_id !== runId) throw new Error('目前工作已變更，請重新取得狀態。');
      render(run);
      if (terminal.has(run.phase)) stop();
      else timer = setTimeout(tick, 1500);
    } catch (error) {
      if (stopped) return;
      stop();
      showError(error); // 查詢失敗不等於後端run已FAILED。
    }
  }
  tick();
  return stop; // 元件卸載時呼叫；不會替使用者取消後端工作。
}

// HR按下核准後：editedJob取自審核表。
async function approveAndStart(editedJob, confirmBeforePublish, render, showError) {
  const run = await api('/agent/approve', {
    job: editedJob,
    hr_confirmed: true,
    confirm_before_publish: confirmBeforePublish,
    scenario: 'SUCCESS'
  });
  await api('/agent/browser/start', { run_id: run.run_id });
  return watchRun(run.run_id, render, showError);
}
```

外層按鈕事件用`try/catch/finally`恢復busy；AbortError顯示「等待逾時，可重試」，連線失敗顯示「服務未連線」。開始產生新建議時隱藏舊的審核表及來源，避免把上次內容當成新結果。

若approve或start發生連線中斷，先GET run確認是否已建立／開始，再讓HR決定下一步；不要盲目重送寫入請求。範本與研究尚未核准的結果目前不保存至GET run，重新整理後需重新產生；核准後可用GET run恢復job。

## 8. 模擬網站的手動表單接口

這組由`/mock104`一般網站使用；若只接HR工作台，無需自行把Agent每一步換成API呼叫。所有回應仍需保留模擬標示。

| 方法與路徑 | body | 成功碼／行為 |
|---|---|---|
| `GET /api/mock104/state` | 無 | 200快照；無session為204 |
| `POST /api/mock104/jobs` | JobForm | 201，新增草稿 |
| `PUT /api/mock104/jobs/{job_id}` | 完整JobForm | 200，只能編輯草稿 |
| `POST /api/mock104/jobs/{job_id}/submit` | `{"scenario":"SUCCESS"}`或FAILURE | 200，待審核 |
| `POST /api/mock104/jobs/{job_id}/approve` | `{}` | 200，處理中 |
| `POST /api/mock104/jobs/{job_id}/complete` | `{}` | 200，依scenario得到成功／失敗 |
| `POST /api/mock104/jobs/{job_id}/retry` | `{"scenario":"SUCCESS"}`或FAILURE | 200，失敗後回待審核，仍須approve及complete |
| `POST /api/mock104/jobs/{job_id}/close` | `{}` | 200，關閉並自求職者預覽移除 |

寫入回傳快照並加上`selected_id`，不是只回一筆job。用`response.jobs.find(j => j.id === response.selected_id)`取得選取職缺。**目前沒有GET /jobs/{id}**，請由state的jobs查找。

```typescript
interface PortalSnapshot {
  jobs: Array<{
    id: string;
    revision: number;
    status: 'DRAFT' | 'PENDING_APPROVAL' | 'PROCESSING'
      | 'SUCCEEDED' | 'FAILED' | 'CLOSED' | 'CANCELLED';
    created_at: string;
    updated_at: string;
    data: JobForm;
    publication: null | Record<string, unknown>;
  }>;
  mode: 'SIMULATION';
  sent_to_platform: false;
  notice: string;
  selected_id?: string;
}
```

publication有值時，重要欄位包含`id`、`request_id`、`status`、`status_label`、`attempts`、`simulated_job_id`、`error_code`、`is_simulated`、`sent_to_platform`及`notice`。成功編號以sim104-開頭，不是真實104職缺網址。完整結構見實測範例。

網站job的SUCCEEDED對應Agent觀察完成後的PUBLISHED；兩者不是同一狀態欄位。手動網站只更新自身資料，不會替Agent直接修改phase。不要只按API回應200就顯示整個Agent流程完成。

狀態順序：`DRAFT → PENDING_APPROVAL → PROCESSING → SUCCEEDED / FAILED`。FAILED可retry回PENDING_APPROVAL，最多三次執行（含第一次）；關閉後為CLOSED。一般網站的approve與complete是兩個請求，並非一呼叫approve就已完成。

## 9. 錯誤與前端反應

業務錯誤為`{"detail":"錯誤訊息"}`；欄位驗證422則通常是`detail`陣列，包含loc、msg、type等資料。不要假定所有錯誤都有相同字串格式。

| HTTP／情況 | 常見原因 | 前端反應 |
|---|---|---|
| 400 | Computer Use網址不是允許的本機來源 | 顯示錯誤，勿改為任意外部網址 |
| 403 | 寫入Origin不同、瀏覽器啟動請求非本機 | 使用同來源proxy／本機部署；不要求使用者輸入模型金鑰 |
| 404 | session到期、run不存在、job不存在或版本已過期 | 依訊息重新開始展示或載入頁面；原暫存資料無持久恢復接口 |
| 409 | run_id過期、phase不符、已有執行工作、草稿已凍結、重試上限 | 重新查run／state，再更新按鈕，不自動改掉HR核准資料 |
| 422 | 缺欄位、薪資規則、description太短、hr_confirmed不是true、公平招募限制 | 對應欄位提示；需求不合適時請HR修改 |
| 429 | 模型整理次數或每分鐘服務上限 | 停止重複送出，提示稍後再試；沒有回傳保證的Retry-After |
| 502 | 搜尋連線、逾時、無來源或格式錯誤 | 顯示失敗，不展示舊建議或聲稱已完成研究 |
| 503 | 模型未啟用、未設金鑰、瀏覽器依賴缺少、展示人數上限 | 顯示可理解的服務訊息，交後端處理設定 |
| 前端AbortError | 15秒一般／範本、60秒研究等待到期 | 恢復按鈕並提示逾時；這不是後端工作狀態 |
| 其他5xx／非JSON | 未預期服務錯誤 | 顯示一般錯誤並恢復busy，保留可排查資訊 |

HTTP 200也可能含`phase: "FAILED"`，查詢本身成功與工作是否成功需分開處理。

## 10. 相容接口與其他後端

### 主工作台不使用的相容項目

- `POST /agent/claim`及`POST /agent/filled`屬先前填表交接，使用RUNNING、READY_TO_PUBLISH等狀態；外部Computer Use不需前端呼叫它們。
- prepare的MODEL模式是既有模型欄位抽取，可能回傳null與missing_fields；SAMPLE只接受CNC固定展示。不要用這兩種回應假設AUTO的來源及欄位都相同。
- `/api/recruitment-demo/*`是另一個固定CNC展示：start、state、approve、complete、retry；Cookie及資料庫均與mock104分開。

### 企業招募後端 `/api/recruitment/*`

PR也有企業／角色隔離的招募後端，但尚非展示Cookie的登入服務。它使用`RECRUITMENT_API_TOKENS_JSON`設定的**服務端Bearer憑證**；不可把憑證存到前端、localStorage或公開環境變數。若要接企業前台，需另定登入與BFF代理方案，本稿不將該方案視為已完成。

| 功能 | 目前主要接口 | 請求模型／備註 |
|---|---|---|
| 平台能力 | `GET /platforms` | 人工紀錄與模擬能力 |
| 招募需求 | `POST /requirements/prepare`、`POST /requests`、`PUT /requests/{id}`、`GET /requests` | DraftInput／Requirement；與AUTO範本prepare不同 |
| 需求核准與關閉 | `POST /requests/{id}/approve`、`POST /requests/{id}/close` | RequestApproval含expected_revision；核准需HR |
| 人工刊登紀錄 | `POST /requests/{id}/publications`、`GET /publications` | Publication；只記錄，不替平台刊登 |
| 模擬刊登 | `POST /requests/{id}/simulated-publications`、`GET /simulated-publications`、`GET /simulated-publications/{id}` | SimulationCreate；需已核准需求 |
| 模擬推進 | `POST /simulated-publications/{id}/approve`、`/complete`、`/retry` | retry用SimulationRetry；HR操作 |
| 授權候選資料 | `POST /requests/{id}/candidates`、`GET /candidates/{id}`、`PUT /candidates/{id}/evidence` | CandidateImport／CandidateEvidence；須授權依據與到期時間 |
| 停止聯絡與清理 | `POST /candidates/{id}/opt-out`、`DELETE /candidates/{id}`、`POST /retention/purge` | 依角色授權，不能視為一般展示操作 |
| 比對 | `POST /applications/{id}/match` | 回傳條件檢核與證據 |
| 邀請草稿與核准 | `POST /applications/{id}/invitations`、`POST /invitations/{id}/approve` | InvitationDraft／InvitationApproval |
| 人工發送與回覆紀錄 | `POST /invitations/{id}/manual-delivery`、`/retry`、`/manual-reply` | Delivery／Reply；不自動傳送平台訊息 |
| 招募階段 | `POST /applications/{id}/stage` | StageChange |
| 看板與列表 | `GET /dashboard`、`GET /applications`、`GET /invitations`、`GET /events` | 列表多使用limit、offset；events是一般JSON，不是SSE |

表中路徑全部相對`/api/recruitment`。完整參數、各模型及Bearer scheme見附檔OpenAPI；業務流程與角色權限見[後端操作文件](RECRUITMENT_BACKEND.md)。企業接口使用實際設定的資料庫，不能拿展示cookie呼叫。

## 11. 前端驗收清單與待確認項目

- [ ] 測試員／大里區／招募三人月薪面議：立即出範本、3人、薪資null，建議欄位有標示。
- [ ] 未收錄職稱：顯示研究狀態，成功有來源；失敗與逾時可恢復按鈕。
- [ ] approve只送JobForm；未核准、薪資不合或工作內容不足時能顯示422。
- [ ] 核准後才啟動瀏覽器，run輪詢不重疊，截圖正確加JPEG data URL前綴。
- [ ] 等待HR確認時才開放繼續；PUBLISHED／FAILED／CANCELLED停止輪詢。
- [ ] session到期或服務重啟顯示需重新建立，不把204當JSON解析。
- [ ] 查詢逾時不誤判為刊登失敗；取消不宣稱已回滾草稿或已發生的刊登。
- [ ] 持續顯示模擬，不產生正式104連結，不把金鑰帶入前端。

待雙方確認：正式版登入與企業代理、持久任務與多worker、回應response_model、統一錯誤碼、run_id獨立查詢、任務／刊登一致性與重試策略、更多地區／工時選項、遠端瀏覽器部署。這些是後續規格議題，不是本稿承諾已實作的接口。
