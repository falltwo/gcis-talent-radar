# 找人 agent（computer use）

HR 輸入職缺需求，agent 依職類挑網站，用 computer use 操作瀏覽器搜尋、點進候選人個人頁、讀取專業，最後回傳每個人的專長摘要和公開連結。流程圖見 [diagrams/sourcing-flow.png](diagrams/sourcing-flow.png)。

即時頁：啟動 `python server.py` 後打開 `http://127.0.0.1:8888/sourcing`，輸入需求就能直接看 agent 操作 Chrome 的即時畫面。

## 分工

| 角色 | 負責 |
|---|---|
| gpt-6-luna（決策） | 判斷職類與技能、決定搜尋框要打什麼、從搜尋結果挑誰點進去、讀完個人頁寫摘要並判斷符不符合（不符合的不列入名單） |
| Jev（computer use） | 實際操作瀏覽器：點搜尋框、打進 gpt-6-luna 決定的字、按 Enter、點進指定候選人、關彈窗 |
| 確定性備案 | Jev 沒完成時改成直接開搜尋結果網址、直接點連結，事件裡會標 `fallback` |

沒有金鑰時全部改用規則版與確定性操作，流程照樣跑完。

一次流程（1 個網站、3 位候選人）大約 6 萬 token：gpt-6-luna 約 1 萬輸入、900 輸出；Jev 約 10 次決定、每次約 5,000 輸入（輸出免費）。依 OpenRouter 價格約 US$0.004。這是估算，尚未用真金鑰量測。

## 安裝與設定

```bash
pip install -r requirements-sourcing.txt   # typesafe-computer-use，需要 Python 3.12 以上
```

- 本機要有 Chrome。Windows、macOS 的預設安裝路徑會自動找到，其他位置用 `CHROME_PATH` 指定。
- `.env` 的 `OPENROUTER_API_KEY` 同時給兩個模型用：
  - **Jev**（`typesafe/jev-1.13`）：決定瀏覽器每一步，例如關掉 cookie 橫幅、彈窗。
  - **gpt-6-luna**：把需求轉成搜尋條件、把個人頁整理成摘要。
- 沒有金鑰也能跑：不處理彈窗，需求改用本地規則判斷，摘要改用規則版（只列頁面上出現的技能）。

| 環境變數 | 預設 | 用途 |
|---|---|---|
| `SOURCING_JEV_MODEL` | `typesafe/jev-1.13` | Jev 模型代碼 |
| `SOURCING_HEADED` | 空 | 設成 `1` 會開出看得到的 Chrome 視窗，方便展示 |
| `SOURCING_PAGE_DELAY` | `1.5` | 每次開頁後等幾秒，讓 JS 頁面渲染，也放慢存取節奏 |
| `CHROME_PATH` | 自動尋找 | Chrome 執行檔路徑 |

## 網站

| 職類 | 網站 | 狀態 |
|---|---|---|
| 軟體開發 | GitHub | 可用 |
| 軟體開發 | Stack Overflow | 搜尋頁用瀏覽器；個人頁會跳 Cloudflare 驗證，改用官方 Stack Exchange API。排行不分地點、API 也不能依地點搜尋：排行上的人一次批次查完（1 次 API），自填地點在需求城市的列入，同國家其他城市列為部分符合，其他略過；指定城市時通常找不到人，會送 `notice` 說明 |
| 軟體開發 | GitLab | **不可用**：Cloudflare 機器人驗證 |
| AI／資料 | GitHub、Hugging Face、Kaggle | 可用（Hugging Face 從模型推回作者） |
| 設計 | Dribbble | 可用（從作品搜尋找作者） |
| 設計 | Behance | **不可用**：對自動瀏覽回應 HTTP 400 |
| 研究 | ORCID | 官方公開 API（不需金鑰，不開瀏覽器）：依研究關鍵字搜尋，城市用「位在該城市的機構」篩（機構名單來自 OpenAlex），附研究關鍵字與研究者網站。網頁版很重、常讓瀏覽器連線逾時，所以不用網頁 |
| 研究 | OpenAlex | 官方 API，不開瀏覽器（取代 Google Scholar）：依主題找近年論文的作者，再用作者**目前**所屬機構篩城市或國家 |
| 所有職類 | 個人網站 | 不主動搜尋；只記錄候選人在個人頁用 `rel="me"` 留的網站 |
| 不碰 | LinkedIn、Google Scholar、104／1111／518／yes123／CakeResume | 條款禁止自動化（含登入後的帳號），或屬付費雇主帳號的履歷庫；不做 computer use。正式管道是 LinkedIn Recruiter System Connect、104 HR Max Open API 等官方合作 |

網站狀態是 2026-11-02 實測的結果。遇到機器人驗證或錯誤頁時，系統會跳過該網站，**不嘗試繞過**。

## API（給前端）

找人 agent 是前端的一個功能，前端只要接下面的 API。完整欄位也可以看 FastAPI 自動產生的 `/docs`。建議用「任務」接口（`/api/sourcing/runs`）：

```js
// 1. 建立任務
const res = await fetch('/api/sourcing/runs', {method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({query: '找會 Python 的軟體工程師，在台中', max_candidates: 5})});
const {run_id, status, events_url} = await res.json();   // 被護欄拒絕時 status 是 rejected，事件裡有原因

// 2. 訂閱事件（GET，可直接用 EventSource；斷線會自動帶 Last-Event-ID 重連，不會漏事件）
const source = new EventSource(events_url);
['plan', 'decision', 'step', 'frame', 'candidate', 'candidate_skipped', 'site_skipped', 'site_error',
 'notice', 'rejected', 'no_public_work', 'error', 'done']
  .forEach(type => source.addEventListener(type, e => handle(JSON.parse(e.data))));
source.addEventListener('end', () => source.close());     // 任務結束、事件送完

// 3. 取消
await fetch(`/api/sourcing/runs/${run_id}`, {method: 'DELETE'});
```

`ui/sourcing.html`（`/sourcing`）就是照這個寫法做的完整示範頁，畫面渲染都在 `handle(event)`。

| 接口 | 說明 |
|---|---|
| `GET /api/sourcing/sites` | 網站目錄：`{"sites": [{"id", "name", "categories", "available", "unavailable_reason"}]}` |
| `POST /api/sourcing/runs` | 建立任務，回 201：`{run_id, status, events_url, snapshot_url, message}`。同時執行的任務達上限回 429，寫不進稽核紀錄回 503，輸入不合規回 422 |
| `GET /api/sourcing/runs/{id}/events` | SSE 事件串流。每個事件有 `id:`（從 1 起算，`frame` 沒有 id）、`event:` 和一行 `data: <JSON>`；結束時送 `event: end`。`?frames=false` 可關掉即時畫面 |
| `GET /api/sourcing/runs/{id}` | 目前狀態：`status`、`plan`、`steps`、`candidates`、`skipped`、`message`、`usage`。前端重新整理頁面後可以用它還原畫面 |
| `DELETE /api/sourcing/runs/{id}` | 取消。背景流程會在下一步停下、關掉 Chrome，最後送出 `done`（`cancelled: true`），狀態變 `cancelled` |
| `POST /api/sourcing/search` | 一次性版本：發請求後直接串流，不能重連或取消；用 `fetch` 自己解析（`EventSource` 不支援 POST） |

`POST /api/sourcing/runs` 的參數：

| 欄位 | 說明 |
|---|---|
| `query` | 2～300 字 |
| `max_candidates` | 1～20，預設 5 |
| `sites` | 選填，只搜這些網站 id；不給就依職類自動挑 |
| `screenshots` | 預設 `false`，每一步另附截圖；即時畫面由事件串流的 `frame` 提供 |

任務 `status`：`running`、`done`、`cancelled`、`error`、`rejected`（公平招募護欄擋下）、`no_public_work`（職類網路上少有公開作品）。

**部署注意**：任務存在後端行程的記憶體裡，結束 30 分鐘後清掉；多個 worker 或重啟後就查不到，正式部署要改成共用儲存。每個任務會開一個 Chrome，同時執行上限用 `SOURCING_MAX_RUNS` 設定（預設 2）。

### 事件

| type | 何時出現 | 主要欄位 |
|---|---|---|
| `rejected` | 需求帶有年齡、性別、國籍等條件，被公平招募護欄擋下（不開瀏覽器） | `reason`、`matched_traits` |
| `no_public_work` | 職類網路上少有公開作品，例如作業員、業務（不開瀏覽器） | `advice`、`plan` |
| `plan` | 開始搜尋前 | `plan`（職類、技能、地點、判斷來源）、`sites` |
| `frame` | `live=true` 時，畫面有變化就送 | `data`（`data:image/jpeg;base64,…`），直接設成 `<img>` 的 `src` |
| `decision` | gpt-6-luna（或規則）做決定時 | `site`、`what`（`search_text` 搜尋字、`pick` 挑人）、`detail`、`by`（`gpt-6-luna` 或 `rules`） |
| `candidate_skipped` | gpt-6-luna 判斷不符合，或 Stack Overflow 自填地點不符（`reason` 以「地點不符」開頭） | `site`、`name`、`reason` |
| `notice` | 沒有金鑰時提醒 | `message` |
| `site_skipped` | 職類對到的網站不可用 | `site`、`reason` |
| `step` | 瀏覽器每做一步 | `n`、`site`、`action`、`detail`、`url`、`screenshot`（`data:image/jpeg;base64,…`，可能是 `null`）、Jev 步驟另有 `confidence`；點擊與打字步驟另有 `geometry`（見下方） |
| `candidate` | 讀完一位候選人 | `candidate`（見下表）；讀個人頁時另有 `geometry`，`box` 是名字在個人頁上的位置 |
| `site_error` | 網站跳驗證、沒找到候選人、API 失敗 | `site`、`reason` |
| `error` | 瀏覽器或套件無法使用 | `reason` |
| `done` | 結束 | `count`、`plan`、`message`、`usage`（實際 token 與費用）、`cancelled` |

`step.action`：`open_entry`（開網站入口頁）、`fallback`（Jev 沒完成，改用備案）、`read_api`（OpenAlex、ORCID、Stack Exchange 官方 API）、`open_search`（開搜尋結果頁）、`jev_click`／`jev_type_text`／`jev_press_enter`／`jev_press_escape`／`jev_scroll_down`／`jev_done`／`jev_none`／`jev_refused`…（Jev 的動作；`jev_refused` 是被安全規則擋下的動作）、`open_profile`（點擊或開啟個人頁）。

`candidate` 欄位：

| 欄位 | 說明 |
|---|---|
| `site`、`profile_url` | 來源網站與個人頁 |
| `name`、`headline` | 顯示名稱、一句話介紹 |
| `skills`、`matched_skills` | 頁面上的技能；其中符合需求的 |
| `summary`、`summary_source` | 專長摘要；`llm`、`rules` 或 `api` |
| `fit`、`fit_reason` | gpt-6-luna 判斷：`符合`、`部分符合`、`未判斷`；判斷根據。官方 API 來的候選人（Stack Overflow、OpenAlex、ORCID）用 API 給的標籤、研究主題、關鍵字判斷 |
| `location` | 候選人自己公開填的地點（目前只有 Stack Overflow），沒有就是空字串 |

所有網址（`profile_url`、`evidence[].url`、`personal_site`）後端都只輸出 `http(s)://`；前端放進 `href` 前也請再檢查一次。

### 座標（`geometry`）

給前端在即時畫面上畫點擊標記與方框。座標是即時畫面（`frame` 事件的圖）上的像素，圖多大就照比例換算：

```json
{"frame": {"w": 1280, "h": 800}, "click": {"x": 640, "y": 400}, "box": {"x": 551, "y": 382, "w": 178, "h": 36}}
```

- `click`：滑鼠點下去的位置（元素中心），只有點擊、打字步驟有。
- `box`：`open_profile` 是搜尋結果上那位候選人的整張卡片；`jev_click`、`jev_type_text` 是被點的元素；`candidate` 事件是個人頁上名字的位置。
- 座標對應的是**動作發生當下**的畫面；點下去之後頁面會換，標記建議顯示 1 秒左右就淡出。
- 找不到位置時不會有 `geometry`，前端要容許缺少。
| `evidence` | `[{label, url}]`，只放頁面上真的存在的連結：個人頁、代表作品、個人網站 |
| `personal_site` | 候選人自己留的網站，沒有就是 `null` |

## 治理

- **一個網站出錯不影響其他網站**：該網站送 `site_error` 後換下一個，已找到的候選人保留；瀏覽器整個壞掉時才送 `error`。
- **不會留下 Chrome**：Windows 上 agent 的 Chrome 和伺服器綁在同一個「伺服器結束就一起結束」的群組，強制結束伺服器也會一起關閉；每個伺服器第一次開 Chrome 前，也會清掉上次殘留的（只認找人 agent 的暫存設定檔 `tscu-chrome-*`，不碰一般 Chrome）。

- **公平招募**：送進護欄前會在需求前面補上「招募」，讓「找 30 歲以下的…」這種寫法也會被擋下。代價是「不要考慮年齡」這種公平的寫法也會被擋（「不限性別」可以通過）。
- **不蒐集聯絡方式**：Email、電話在進模型和輸出前都會移除。
- **稽核**：每次請求寫一筆 `reports/agent_audit.jsonl`，只存需求的 SHA-256、結果與用到的網站，不存原文與候選人名單。
- **Jev 的權限**：可以點擊、捲動、按 Esc、返回；只能在搜尋框打字（欄位名稱要像搜尋框，密碼欄一律拒絕），要打的字由 gpt-6-luna 決定，不是 Jev 自己產生；打完字才能按 Enter；「開網址」只能回到該網站的入口頁；要點的連結會離開網站就拒絕，真的離開了就退回。
- **網站條款**：只讀公開頁面，只給連結。GitHub 等網站禁止把蒐集到的資料拿去寄未經同意的信，聯絡前請自行確認候選人的公開意願。

## 限制

- 職類判斷是關鍵字規則，有金鑰時再由模型補強；寫得太模糊時會回 `no_public_work` 並請使用者寫明職缺或技能。
- 搜尋品質取決於各網站自己的搜尋：Stack Overflow 依標籤排名，不能依地點篩選；Hugging Face 依模型名稱搜尋。
- 只讀搜尋結果的第一頁；目前一次只開一個分頁，一位一位讀，5 位候選人大約要 30～60 秒。
- Jev 與 gpt-6-luna 要有金鑰才會執行；目前只用模擬資料驗證過邏輯，尚未用真金鑰實測。沒有金鑰的確定性版本已在真實網站跑過（含即時畫面）。
