**繁體中文** | [English](README.en.md)

# 產業人才雷達

工廠要擴廠、要招人之前，老闆通常會想問：附近同業在增加還是在退場？這一區現在有多少職缺？薪資大概在什麼水準？產業人才雷達用政府開放資料回答這些問題。每個數字都標明出處和資料期別，資料沒有的，系統就直說沒有。

這是 2026 InnoServe 資訊應用服務創新競賽「商業治理 AI 創新組（GCIS-OD）」的參賽作品，以臺中製造業為示範範圍。

![首頁問答：大雅區製造業職缺](docs/images/answer.png)

## 它能回答什麼

| 問題 | 用的資料 | 粒度 |
|---|---|---|
| 這一區的同業在新設、增資，還是解散？ | 經濟部商工登記：公司設立／變更登記清冊（依稅籍行業代號對到製造業中類） | 臺中行政區 × 製造業中類 × 月 |
| 這一區有幾家工廠？ | 臺中市經發局工廠產業類別家數（[data.gov.tw 174209](https://data.gov.tw/dataset/174209)） | 行政區 × 產業類別 × 月 |
| 這一區現在有多少公開職缺？ | 台灣就業通職缺清單（[data.gov.tw 44062](https://data.gov.tw/dataset/44062)） | 行政區，每日快照 |
| 全市製造業新設公司趨勢？ | 經濟部商工行政資料開放平臺：按行業別及縣市別分的公司新設統計 | 臺中全市 × 行業大類 × 月 |
| 薪資大概在什麼水準？ | 勞保局投保薪資統計（[data.gov.tw 100999](https://data.gov.tw/dataset/100999)） | 臺中全市 × 行業大類 × 年末 |

資料粒度不同，就不混在一起推。全市數字不會拆到行政區，職缺數不等於缺工人數，投保薪資也不等於實領薪資。

## 怎麼做到「數字有出處」

```
提問 → 範圍檢查 → 公平招募檢查 → 模型選工具 → 程式查官方資料 → 模型撰寫回答 → 數字核對 → 回答＋查證紀錄
                     │ 不放行就拒答，不呼叫模型                         │ 數字對不上就整段攔下
                     └──────────── 每一步都寫入稽核紀錄（只存雜湊值）────────────┘
```

1. **數字由程式算，模型只負責理解和說明。** 模型透過 function calling 呼叫唯讀資料工具，工具把數值、資料期別、來源網址和限制一起回傳。
2. **送出前逐一核對數字。** `agent/numeric_verifier.py` 會把回答裡的每個數字、日期拿去比對工具結果。只要有一個對不上，整段回答就攔下，不顯示模型自己的說法。
3. **招募公平護欄。** 依《就業服務法》第 5 條，凡是用年齡、性別、國籍、身心狀況、宗教等個人特徵篩選或決定錄用的要求，都會在呼叫模型前拒答（`agent/prompt_guard.py`）。但如果是在問「如何避免年齡歧視」這類問題，可以正常通過。
4. **稽核紀錄只存雜湊值。** 每次提問都會寫入 `reports/agent_audit.jsonl`，內容只有問題的 SHA-256、字數、規則結果、用到的工具和核對狀態，不存原文、回答或金鑰。日誌寫不進去，就停止回答（API 回傳 503）。
5. **查證紀錄攤開給使用者看。** 每個回答下方都能展開，看系統查了哪一份資料、怎麼算的、有哪些限制。

![查證紀錄](docs/images/trace.png)

## 趨勢預測只給範圍

預測引擎在 `forecast/`。每條序列都先跑最簡單的基線，再比複雜模型，用 rolling-origin 回測選模型，對外只輸出 80% 區間，不給單一數字。

| 序列 | 期間 | 回測起點 | 選中模型 | MAE | 對照：季節 Naive |
|---|---|---:|---|---:|---:|
| 臺中製造業新設公司家數 | 2012-06～2026-08（171 個月） | 45 | Chronos-Bolt-tiny | 24.1 家 | 27.9 家 |
| 公立就業服務新登記求才人數 | 2022-01～2026-06（54 個月） | 6 | 季節 Naive | 917.5 人 | — |

新模型不一定比較好：求才人數這條，季節 Naive 贏過 Chronos。2026-09 全市製造業新設公司的 80% 區間是 61～95 家。回測方法、指標和官方缺月的補回方式，見 [docs/FORECAST_ENGINE.md](docs/FORECAST_ENGINE.md)。

## 快速開始

需要 Python 3.10 以上。AI 問答要有 OpenRouter API key。

```bash
git clone https://github.com/falltwo/gcis-talent-radar.git
cd gcis-talent-radar
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn pandas numpy requests xlrd openpyxl statsmodels pytest

cp .env.example .env      # 在 .env 填入 OPENROUTER_API_KEY
python server.py
```

打開 `http://127.0.0.1:8888/`。如果 8888 被占用，`server.py` 會改用其他埠，並把網址印出來。

- 金鑰只由後端讀取。不要放進 `ui/`、前端環境變數或 Git；`.env` 已經列在 `.gitignore`。
- 預設模型是 `openai/gpt-6-luna`，可以用 `OPENROUTER_MODEL` 換掉。
- 沒有金鑰也能啟動，首頁的擴廠情境卡和各個 `/api/official/*` 端點照樣可以用。

### 重新整理資料

```bash
python -m etl.run_real_etl                     # 下載（已下載的跳過）＋整理＋品質報告
python -m etl.run_real_etl --only taiwanjobs   # 只抓當天的就業通職缺快照
python -m forecast.run_real --series gcis --horizon 12 --step 3
```

每次執行都會更新 `data/raw/_manifest.csv`（原始檔網址、時間、SHA-256）、`data/processed/_catalog.json` 和 `reports/DATA_QUALITY.md`。細節見 [docs/04-ETL.md](docs/04-ETL.md)。

### 測試

```bash
python -m pytest tests -q
```

目前共 345 項測試，涵蓋資料整理、資料工具、預測、護欄與稽核。GitHub Actions 會在每個 PR 和 push 到 `main` 時執行。

## 頁面與 API

| 路徑 | 內容 |
|---|---|
| `/` | 首頁：直接問答＋擴廠情境（預設大雅區、招募 10 人） |
| `/demo` | 擴廠情境單頁版 |
| `/docs` | FastAPI 自動產生的 API 文件 |
| `POST /api/agent/chat` | AI 問答 |
| `GET /api/demo/expansion` | 擴廠情境的四個官方數字 |
| `GET /api/official/job-demand`、`company-trend`、`wage-baseline` | 三個官方資料工具 |
| `/legacy` | 舊版原型，含模擬資料，不屬於展示內容 |

## 專案結構

```
agent/      問答流程：範圍檢查、公平護欄、工具呼叫、數字核對、稽核
engine/     資料工具（官方資料查詢）
etl/        真實資料下載與整理（etl/sources/ 一個來源一個模組）
forecast/   預測引擎與回測
api/        FastAPI 路由
ui/         前端頁面
data/       原始檔與整理後的資料表
reports/    資料品質報告、預測結果、稽核日誌
tests/      pytest
docs/       設計與資料文件
```

## 限制

- **舊資料表裡還有模擬資料。** 這個 repo 改造自早期原型。產業動能、供需錯配、部分高教推估等表仍是模擬或推估值，清單見 [docs/SIMULATED_DATA.md](docs/SIMULATED_DATA.md)。助理用到這些工具時，會在回答中標明「模擬資料」。首頁展示的數字都來自上表的官方資料。
- **職缺快照有上限。** 就業通 API 每次查詢最多回傳 1,000 筆，碰到上限的行政區，總數會偏少。職缺的產業別是用職稱和職類關鍵字比對出來的，不是雇主的正式登記行業。
- **護欄是規則，不是模型。** 範圍檢查和公平護欄都是本地的關鍵字／正規表示式規則，可能誤判或漏判，不能當成法律合規認證。第二道把關（依自訂政策判斷的安全模型）還在開發分支測試，尚未合併。
- **數字核對只檢查數值。** 它確認回答裡的數字能在工具結果找到，但不代表語意、單位都正確。

## 文件

- [docs/04-初賽展示主線.md](docs/04-初賽展示主線.md)：展示操作路徑與數字來源
- [docs/05-三項官方資料工具實作.md](docs/05-三項官方資料工具實作.md)：三個官方資料工具的口徑與驗收
- [docs/GOVERNANCE.md](docs/GOVERNANCE.md)：護欄執行順序、稽核欄位
- [docs/FORECAST_ENGINE.md](docs/FORECAST_ENGINE.md)：預測模型、回測、官方缺月修復
- [docs/04-ETL.md](docs/04-ETL.md)：資料表清單與 ETL 執行方式
- [docs/SIMULATED_DATA.md](docs/SIMULATED_DATA.md)：還沒換掉的模擬資料

## 資料來源與授權

使用的政府資料依[政府資料開放授權條款](https://data.gov.tw/license)利用，來源包括經濟部商工行政資料開放平臺、政府資料開放平臺、臺中市政府經濟發展局、勞動部勞動力發展署、勞動部勞工保險局。

本專案目前沒有附開源授權條款，著作權由作者保留。

本專案改造自 [DrChunChihChen/taichung-industry-talent-radar](https://github.com/DrChunChihChen/taichung-industry-talent-radar)。
