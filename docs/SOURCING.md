# 找人 agent（computer use）

HR 輸入職缺需求，agent 依職類挑網站，用 computer use 操作瀏覽器搜尋、點進候選人個人頁、讀取專業，最後回傳每個人的專長摘要和公開連結。流程圖見 [diagrams/sourcing-flow.png](diagrams/sourcing-flow.png)。

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
| 軟體開發 | Stack Overflow | 搜尋頁用瀏覽器；個人頁會跳 Cloudflare 驗證，改用官方 Stack Exchange API 讀公開資料 |
| 軟體開發 | GitLab | **不可用**：Cloudflare 機器人驗證 |
| AI／資料 | GitHub、Hugging Face、Kaggle | 可用（Hugging Face 從模型推回作者） |
| 設計 | Dribbble | 可用（從作品搜尋找作者） |
| 設計 | Behance | **不可用**：對自動瀏覽回應 HTTP 400 |
| 研究 | ORCID | 可用（頁面較慢，常有 cookie 橫幅） |
| 研究 | OpenAlex | 官方 API，不開瀏覽器（取代 Google Scholar）：依主題找近年論文的作者，再用作者**目前**所屬機構篩城市或國家 |
| 所有職類 | 個人網站 | 不主動搜尋；只記錄候選人在個人頁用 `rel="me"` 留的網站 |
| 不碰 | LinkedIn、Google Scholar、104／1111／518／yes123／CakeResume | 條款禁止自動化（含登入後的帳號），或屬付費雇主帳號的履歷庫；不做 computer use。正式管道是 LinkedIn Recruiter System Connect、104 HR Max Open API 等官方合作 |

網站狀態是 2026-11-02 實測的結果。遇到機器人驗證或錯誤頁時，系統會跳過該網站，**不嘗試繞過**。

## API

### `GET /api/sourcing/sites`

回傳網站目錄：`{"sites": [{"id", "name", "categories", "available", "unavailable_reason"}, ...]}`。

### `POST /api/sourcing/search`

```json
{"query": "找會 Python 的後端工程師，在台中", "max_candidates": 5, "sites": ["github"], "screenshots": true}
```

| 欄位 | 說明 |
|---|---|
| `query` | 2～300 字 |
| `max_candidates` | 1～20，預設 5 |
| `sites` | 選填，只搜這些網站 id；不給就依職類自動挑 |
| `screenshots` | 預設 `true`，每一步附截圖 |

回應是 **Server-Sent Events**（`text/event-stream`）。每個事件是 `event: <type>` 加一行 `data: <JSON>`。寫不進稽核紀錄時回 HTTP 503，輸入不合規回 422。

前端用 `fetch` 讀串流（`EventSource` 不支援 POST）：

```js
const res = await fetch('/api/sourcing/search', {method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({query, max_candidates: 5})});
const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
let buf = '';
for (;;) {
  const {value, done} = await reader.read();
  if (done) break;
  buf += value;
  let i;
  while ((i = buf.indexOf('\n\n')) >= 0) {
    const frame = buf.slice(0, i); buf = buf.slice(i + 2);
    const data = JSON.parse(frame.split('\n').find(l => l.startsWith('data: ')).slice(6));
    handle(data);   // data.type 同 event 名稱
  }
}
```

### 事件

| type | 何時出現 | 主要欄位 |
|---|---|---|
| `rejected` | 需求帶有年齡、性別、國籍等條件，被公平招募護欄擋下（不開瀏覽器） | `reason`、`matched_traits` |
| `no_public_work` | 職類網路上少有公開作品，例如作業員、業務（不開瀏覽器） | `advice`、`plan` |
| `plan` | 開始搜尋前 | `plan`（職類、技能、地點、判斷來源）、`sites` |
| `notice` | 沒有金鑰時提醒 | `message` |
| `site_skipped` | 職類對到的網站不可用 | `site`、`reason` |
| `step` | 瀏覽器每做一步 | `n`、`site`、`action`、`detail`、`url`、`screenshot`（`data:image/jpeg;base64,…`，可能是 `null`）、Jev 步驟另有 `confidence` |
| `candidate` | 讀完一位候選人 | `candidate`，見下表 |
| `site_error` | 網站跳驗證、沒找到候選人、API 失敗 | `site`、`reason` |
| `error` | 瀏覽器或套件無法使用 | `reason` |
| `done` | 結束 | `count`、`plan`、`message` |

`step.action`：`read_api`（OpenAlex、Stack Exchange 官方 API，`screenshot` 可能是 `null`）、`open_search`（開搜尋頁）、`jev_click`／`jev_press_escape`／`jev_scroll_down`／`jev_done`／`jev_none`…（Jev 決定的動作）、`open_profile`（點擊或開啟個人頁）。

`candidate` 欄位：

| 欄位 | 說明 |
|---|---|
| `site`、`profile_url` | 來源網站與個人頁 |
| `name`、`headline` | 顯示名稱、一句話介紹 |
| `skills`、`matched_skills` | 頁面上的技能；其中符合需求的 |
| `summary`、`summary_source` | 專長摘要；`llm`、`rules` 或 `api` |
| `evidence` | `[{label, url}]`，只放頁面上真的存在的連結：個人頁、代表作品、個人網站 |
| `personal_site` | 候選人自己留的網站，沒有就是 `null` |

## 治理

- **公平招募**：送進護欄前會在需求前面補上「招募」，讓「找 30 歲以下的…」這種寫法也會被擋下。代價是「不要考慮年齡」這種公平的寫法也會被擋（「不限性別」可以通過）。
- **不蒐集聯絡方式**：Email、電話在進模型和輸出前都會移除。
- **稽核**：每次請求寫一筆 `reports/agent_audit.jsonl`，只存需求的 SHA-256、結果與用到的網站，不存原文與候選人名單。
- **Jev 的權限**：只能點擊、捲動、按 Esc；不能打字、不能送出表單；要點的連結會離開該網站就停止，真的離開了就退回。
- **網站條款**：只讀公開頁面，只給連結。GitHub 等網站禁止把蒐集到的資料拿去寄未經同意的信，聯絡前請自行確認候選人的公開意願。

## 限制

- 職類判斷是關鍵字規則，有金鑰時再由模型補強；寫得太模糊時會回 `no_public_work` 並請使用者寫明職缺或技能。
- 搜尋品質取決於各網站自己的搜尋：Stack Overflow 依標籤排名，不能依地點篩選；Hugging Face 依模型名稱搜尋。
- 只讀搜尋結果的第一頁；目前一次只開一個分頁，一位一位讀，5 位候選人大約要 30～60 秒。
- Jev 的瀏覽器步驟要有金鑰才會執行；目前只用模擬資料驗證過邏輯，尚未用真金鑰實測。
