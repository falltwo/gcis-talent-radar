> **InnoServe 2026 改造版**：初賽互動展示請開本機 FastAPI 的 `/demo`，操作與資料口徑見 [docs/04-初賽展示主線.md](docs/04-初賽展示主線.md)。產品定位見 [docs/01-產品定位.md](docs/01-產品定位.md)，資料集清單見 [docs/02-資料集.md](docs/02-資料集.md)，資料審查見 [docs/03-資料集審查.md](docs/03-資料集審查.md)。以下為原始專案說明，部分舊資料和 AI 敘述未經改造版驗證，不能當成已完成功能。

# 區域產業 × 高教人才供需錯配預警系統 (System Specification v1.0)
## Regional Industry–Talent Structural Mismatch Early-Warning System
### 2026 InnoServe 資訊應用服務創新競賽【經濟部商工登記資料應用組 (GCIS-OD)】

[![Live System](https://img.shields.io/badge/Live_System-taichung--talent--radar.netlify.app-blue?style=flat&logo=netlify)](https://taichung-talent-radar.netlify.app)
[![Live Architecture](https://img.shields.io/badge/Live_Architecture-Interactive_Panel-purple?style=flat&logo=terminal)](https://taichung-talent-radar.netlify.app/architecture)
[![InnoServe 2026](https://img.shields.io/badge/Competition-InnoServe_2026_GCIS--OD-blue.svg)](https://innoserveawards.tca.org.tw/advertise26_GCIS-OD.htm)
[![Golden Benchmark](https://img.shields.io/badge/Golden_Benchmark-65%2F65_Passed_(100%25)-emerald.svg)](benchmark/golden_questions.json)
[![ETL Quality](https://img.shields.io/badge/ETL_Quality_Audit-8%2F8_Passed-success.svg)](tests/test_etl_quality.py)
[![Impeccable Design](https://img.shields.io/badge/Design_Audit-0_Anti--patterns-brightgreen.svg)](ui/index.html)
[![Deterministic Engine](https://img.shields.io/badge/Principles-P1--P5_Guaranteed-orange.svg)](docs/SYSTEM_SPECIFICATION.md)

---

## 🌐 線上部署展示站點 (Live Public URLs)

- 🚀 **系統正式上線網址（決策戰情室）：** [https://taichung-talent-radar.netlify.app](https://taichung-talent-radar.netlify.app)
- ⚡ **實時動態架構儀表板（Live Panel）：** [https://taichung-talent-radar.netlify.app/architecture](https://taichung-talent-radar.netlify.app/architecture)
- 📦 **GitHub 開放原始碼儲存庫：** [https://github.com/DrChunChihChen/taichung-industry-talent-radar](https://github.com/DrChunChihChen/taichung-industry-talent-radar)

---

## 📌 快速交接與規格文件導覽 (Documentation Index)

為協助團隊交接與競賽答辯，本專案提供全套高規格技術文件與動態儀表板：

| 文件名稱 | 主要內容 | 適用對象 |
| :--- | :--- | :--- |
| 🚀 **[系統正式上線戰情室](https://taichung-talent-radar.netlify.app)** | **Lieflat Charts × Impeccable** 淺色紙質系戰情室、Hello IR 乾淨問問入口、雙軸動能氣壓計、四象限錯配散布圖 | 競賽評審、政府決策者、校務主管 |
| ⚡ **[系統實時動態架構儀表板](https://taichung-talent-radar.netlify.app/architecture)** | **live-panel** 打造之動態終端監控架構（導線粒子動效、實時遙測日誌、狀態機翻轉） | 競賽評審、架構師、技術團隊 |
| 📘 **[完整系統規劃書](docs/SYSTEM_SPECIFICATION.md)** | 系統願景、P1–P5 五大原則、資料架構、數理公式推導、四象限錯配矩陣、Agent 五道護欄、Lieflat 前端規範 | 指導教授、競賽評審、架構師 |
| 💻 **[檔案與資料庫架構規格書](docs/FILE_SPECIFICATION.md)** | 完整目錄樹狀圖、Python 模組職責表、SQLite 8 張表完整資料字典、Data Mart CSV 規格、RESTful API 規格 | 後端開發者、資料工程師 |
| 🚀 **[學生交接手冊與競賽衝刺指南](docs/STUDENT_HANDOVER_GUIDE.md)** | 3 分鐘快速本機跑起來、一鍵重跑資料管線、新產業/新工具擴充教學、評審必考 QA 題庫攻防秘笈 | 接手學生團隊、參賽答辯者 |

---

## 一、系統核心價值與實證問題

本系統整合**經濟部商工行政開放平臺（GCIS）公司登記歷史母體**、**教育部校務資訊公開平臺（MOE UDB）**、**內政部戶政司人口推估（少子化生源精算）**與**教育部 UCAN 大專校院就業職能架構**，為地方治理與高教決策建立「區域產業動能 × 高教人才供給」分析架構。

本系統的核心目標不是預測短期職缺，而是建立：
> **Regional Industry–Talent Structural Mismatch Early-Warning System（區域產業 × 高教人才結構性錯配預警系統）**

### 核心回答四大實證問題：
1. **台中市哪些產業正在顯著擴張或動能收縮？**（依據新設率 Entry Rate 與資本擴張率 Capital Expansion Rate）
2. **哪些行政區的特定產業活動較強？**（以西屯、潭子、南屯、大雅等 29 行政區之需求端企業存量與動能展現）
3. **與各產業相關的高教人才供給至 117 學年度可能如何變化？**（少子化虎年海嘯谷底生源池萎縮 -17.02% 與各系所異質消長）
4. **哪些產業出現「產業擴張動能」與「人才供給動能」不同步的結構性警示？**（Mismatch = Demand - Supply 四象限警示）

---

## 二、系統遵循之五項核心原則 (Design Principles)

```
┌─────────────────────────────────────────────────────────────┐
│                    FIVE SYSTEM PRINCIPLES                   │
├─────────────────────────────────────────────────────────────┤
│ P1. Deterministic First (確定性第一，數字全由程式精算)     │
│ P2. LLM Does Not Calculate (LLM 絕對不計算任何數值)         │
│ P3. Constrained Tools (模型選工具；產業與學門映射用固定規則)│
│ P4. Traceable (所有輸出具備 5 級確定性佐證回溯鏈)          │
│ P5. Warning, Not Prediction (定位為結構性預警，非就業預測)  │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、快速開始（3 分鐘啟動）

### 1. 安裝環境需求
```bash
# 建議 Python 3.10 或更高版本
pip install fastapi uvicorn pandas numpy requests
# 完整本機測試（含預測基準測試）
pip install pytest statsmodels
```

### 2. 啟用問答並啟動本機伺服器

AI 問答由 FastAPI 後端呼叫 OpenRouter。請先在後端執行環境設定 API key，再啟動伺服器；不要把 key 放進 `ui/`、Netlify 前端環境變數或 Git：

```bash
cp .env.example .env
# 將 OPENROUTER_API_KEY 設在本機 .env 檔中
export OPENROUTER_MODEL="openai/gpt-6-luna"
python3 server.py
```

也可以直接用 shell 環境變數設定 `OPENROUTER_API_KEY`。伺服器會優先採用 shell 中已設定的值；本機 `.env` 已列入 `.gitignore`。

打開瀏覽器訪問：**`http://127.0.0.1:8888`**。

`OPENROUTER_MODEL` 可依 OpenRouter 帳戶可用的模型代碼調整。前端呼叫同源 `/api/agent/chat`，API key 僅由後端讀取。若只部署 Netlify 靜態前端，AI 問答不會自動可用；需另行部署 FastAPI，並配置前端 API 網址／反向代理與後端環境變數。目前靜態頁仍使用相對路徑 `/api/agent/chat`，尚未提供 Netlify Functions 或跨站 API 設定。

模型可直接呼叫三個官方資料工具：

| 工具 | 意圖 | 資料口徑 |
| --- | --- | --- |
| `get_regional_job_demand` | `JOB_DEMAND_QUERY` | 台灣就業通當期可觀測職缺，可按行政區及職務文字篩選 |
| `get_gcis_new_company_trend` | `COMPANY_TREND_QUERY` | 台中全市按行業大類的新設公司月序列，缺月不補零 |
| `get_wage_baseline` | `WAGE_QUERY` | 台中全市年末勞保投保人數、單位數及平均投保薪資 |

工具回傳的資料限制、來源網址、資料期間會保留在模型上下文與回答佐證中。職缺不等於實際缺工，公司新設不等於招募需求，投保薪資不等於實領薪資。`agent_service.py` 只保留相容入口，實際工作委派給 `llm_agent.py`；範圍判斷由本地 `KeywordScopeGuard` 執行。`server.py` 同時保留 UTF-8 主控台設定及 `.env` 載入，既有環境變數優先。

這個整合只替換問答的意圖理解、工具選擇及文字生成；底層資料表尚未全部換成審查文件列出的公開資料，產業動能和錯配結果含模擬資料。不能據此宣稱能預測個別公司招募成功率或可招到人數。數字比對只檢查回答數字是否能在工具資料找到，不代表語意、單位或來源已驗證。

問答入口會先經過 關鍵字範圍判斷（KeywordScopeGuard）與招募公平 Prompt Guard。涉及依性別、年齡、國籍、身心狀況、宗教等個人特徵篩選或決定錄用的問題會在呼叫模型前拒答；明確詢問如何避免歧視或了解就業保障規範的提問可通過 Prompt Guard。拒答、模型回答與數字核驗結果會追加到 `reports/agent_audit.jsonl`。日誌只保留問題 SHA-256、字元數、政策命中、工具與核驗狀態，不寫入原始問題；可用 `AGENT_AUDIT_LOG_PATH` 指定其他檔案位置。若稽核檔無法寫入，請求會停止並回傳服務錯誤。

### 治理實作與欄位遷移（PR #6）

範圍判斷與 Prompt Guard 都是本地關鍵字／正規表示式規則，沒有串接 TypeSafe 或其他治理模型。`rule_score` 是規則加權分數，不是正確率；不再回傳虛構的 `confidence`，延遲使用實際計時。規則可能誤判或漏判，測試通過僅代表已列案例通過，不代表完整語意理解、法律合規認證或 prompt injection 防護。

- 模組／類別：舊 `agent.jev_model.JevDecisionModel` 移至 `agent.keyword_scope_guard.KeywordScopeGuard`，實例為 `keyword_scope_guard`；不保留舊 import 別名。
- 回應：舊 `governance.jev` 改成 `governance.scope_guard`。`model`／`confidence` 改為 `implementation`／`version`／`rule_score`；頂層 `model` 仍代表 OpenRouter 回答模型。
- 稽核：新事件含 `schema_version: 2`，`jev` 改為 `scope_guard`，拒絕原因碼改為 `KEYWORD_SCOPE_REJECTED`。既有 JSONL 保持原樣；讀取舊檔時以缺少 `schema_version` 辨識舊格式，再將 `jev` 映射到舊版規則結果，勿解讀為模型判斷。
- 允許問題會先記錄 `REQUEST_ACCEPTED`，再呼叫模型，完成後另記錄結果事件；兩者可按問題雜湊與時間比對（事件 ID 不同）。回應的 `audit_id` 指向結果事件。日誌寫入失敗會停止請求。
- 範圍放行不表示有資料作答。沒有工具證據時保留證據閘門，攔下模型自行生成的招募數字或法律內容並提示資料限制。

驗收：`python -m pytest tests -q`。指定 17 題、額外 10 題及同類變體見 `tests/test_governance_acceptance.py`，包含護欄判斷、mock 模型呼叫順序和稽核測試。既有 main 測試保持原樣。歷史架構文件以本段及 [治理說明](docs/GOVERNANCE.md) 為準。

### 3. 一鍵全流程重跑管線與驗證
```bash
python3 pipeline/run_full_pipeline.py
```
自動執行 8 步驟：資料庫初始化 $\rightarrow$ GCIS 洗淨 $\rightarrow$ MOE UDB 提取 $\rightarrow$ UCAN 稀釋 $\rightarrow$ 數理引擎精算 $\rightarrow$ ETL 品質測試 $\rightarrow$ 65 題基準驗證。

---

## 四、前端介面與視覺系統實拍 (Impeccable × Lieflat Charts)

系統遵循 `pbakaus/impeccable` 規範與 `larashero3-dotcom/lieflat-charts` 設計哲學，採用**紙質米白溫潤淺色系（Warm Paper Ivory `#FAF8F5`）**、**四段式圖表架構**、**Lupi Editorial 表格**與 **Glance 巨幅數字**：

### 1. 首頁問問入口（Hello IR 乾淨入口 + Glance KPI + Dual Momentum Barometer）
![Hello IR 首頁](reports/lieflat_overview_full.png)

### 2. 產業動態觀測（Entry Rate 折線圖 + 增資膠囊直條圖）
![產業動態觀測](reports/lieflat_dynamics_tab.png)

### 3. 台中 29 區空間地圖（行政區企業存量排行與水平膠囊長條圖）
![台中空間地圖](reports/lieflat_map_tab.png)

### 4. 高教生源推估（117 年虎年大谷底生源海嘯對比）
![高教生源推估](reports/lieflat_supply_tab.png)

### 5. 供需錯配四象限觀測儀（零軸交叉散布圖與 7 大目標產業佐證卡片）
![供需錯配四象限](reports/lieflat_mismatch_tab.png)

### 6. OpenRouter GPT-6 Luna 資料助理（受限工具呼叫與數字比對）
![AI 決策代理人](reports/lieflat_agent_tab.png)

### 7. 系統實時動態架構儀表板 (Live-Panel Architecture Diagram)
> 由 **`ythx-101/live-panel`** 技能編譯生成之純 HTML/CSS/JS 實時動態監控架構頁面，具備固定佈局、高亮導線粒子動效、即時滾動遙測日誌與狀態機翻轉。

![系統實時動態架構儀表板](reports/architecture_live_panel.png)

👉 **線上動態體驗入口**：[architecture/index.html](architecture/index.html) 或本機訪問 `http://127.0.0.1:8888/architecture`

---

## 五、七大目標產業定義與動能基準 (113年度)

| 產業代碼 | 目標產業名稱 | 登記存量 | 新設率 | 資本擴張率 | 需求動能 ($Z_{demand}$) | 供給動能 ($Z_{supply}$) | 錯配值 ($Mismatch$) | 象限與預警 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`IND_ICT`** | 資訊軟體與數位科技 | 22,065 | 10.94% | 7.76% | **+1.2416** | +0.3120 | **+0.9296** | Q1: 雙重擴張 (Medium) |
| **`IND_SEM`** | 半導體與綠能科技 | 13,524 | 7.70% | 9.80% | **+1.0392** | +1.2829 | **-0.2437** | Q1: 雙重擴張 (Low) |
| **`IND_BIOMED`**| 生技醫療與精準健康 | 10,184 | 7.82% | 7.29% | **+0.5272** | +0.1373 | **+0.3899** | Q1: 雙重擴張 (Low) |
| **`IND_PRO_FIN`**| 專業商管與金融服務 | 23,229 | 6.08% | 4.67% | **-0.3674** | -0.1062 | **-0.2612** | Q3: 雙重收縮 (Low) |
| **`IND_TOUR_CULT`**| 數位文創與觀光休閒 | 15,044 | 6.30% | 3.72% | **-0.5255** | -1.8065 | **+1.2810** | **Q2: 嚴重短缺 (High)** |
| **`IND_MFG`** | 智慧製造與精密機械 | 45,998 | 3.54% | 4.30% | **-0.9466** | +0.7801 | **-1.7267** | **Q4: 相對過剩 (High)** |
| **`IND_TRADE_LOG`**| 國際貿易與現代物流 | 24,240 | 3.84% | 3.91% | **-0.9684** | -0.6006 | **-0.3678** | Q3: 雙重收縮 (Low) |

---

## 六、代碼品質與驗收標準

- **Impeccable 原生檢查**：
  ```bash
  ./.agents/skills/impeccable/scripts/impeccable detect ui/index.html
  # Exit Code: 0, 0 anti-patterns, 0 warnings
  ```
- **黃金標準 65 題評測**：
  ```bash
  python3 benchmark/run_benchmark.py
  # Total: 65, Passed: 65, Accuracy: 100.0%
  ```
- **ETL 品質稽核**：
  ```bash
  python3 tests/test_etl_quality.py
  # Checks Passed: 8/8 (100.0%)
  ```

---

## 七、版權與參賽宣告

本專案由參賽團隊為 **2026 InnoServe Awards** 開發，依據經濟部商工行政開放平臺資料與教育部校務資訊公開平臺規範建置。未經授權禁止商業轉載。
