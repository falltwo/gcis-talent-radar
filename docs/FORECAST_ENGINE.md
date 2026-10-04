# 預測引擎（Step 3）

程式在 `forecast/`，測試在 `tests/test_forecast.py` 與 `tests/test_forecast_real.py`。

## 原則

1. **先有基線，再上複雜模型。** 每條序列都先跑最簡單的方法（延續最後一期、延續去年同期、延續平均變化），複雜模型要贏過它們才有意義。
2. **誤差數字一律來自回測。** 不用訓練期的配適度。
3. **對外只給區間。** 公開輸出只有 80% 與 95% 區間，沒有單一預測值。完整分位數只存在內部檔案，給數值驗證器使用。

## 模型

| 名稱 | 說明 | 區間怎麼來 | 依賴 |
|---|---|---|---|
| `naive` | 延續最後一期 | 常態近似，σ√h | numpy |
| `snaive` | 延續去年同期（月資料 12 期、季資料 4 期） | 常態近似，σ√(k+1) | numpy |
| `drift` | 延續歷史平均變化 | 常態近似，σ√(h(1+h/T)) | numpy |
| `ets` | 指數平滑；在「無趨勢／阻尼趨勢」×「無季節／加法季節」中用 AIC 選型 | 模擬 2,000 條路徑取分位數 | statsmodels |
| `arima` | KPSS 檢定決定是否差分，p、q ≤ 2 用 AIC 選階 | 常態近似 | statsmodels |
| `chronos` | Amazon Chronos-Bolt，zero-shot，只看訓練期資料 | 模型直接輸出分位數（只支援 0.1–0.9，**沒有 95% 區間**） | chronos-forecasting、torch |

基線公式參考 Hyndman & Athanasopoulos《Forecasting: Principles and Practice》3rd ed. §5.5。

## 回測

- 方法：rolling-origin（expanding window）。每個預測起點 t 只用 `y[:t]` 訓練，預測之後 `horizon` 期，再跟實際值比較。測試 `test_backtest_trains_only_on_past` 驗證了這一點。
- 所有模型使用同一組起點。
- 指標：

| 指標 | 意思 | 怎麼讀 |
|---|---|---|
| MAE、RMSE | 中位數預測的平均誤差 | 跟原序列同單位 |
| MASE | 誤差 ÷ 訓練期「延續去年同期」的一步誤差 | < 1 代表比最簡單的方法好 |
| sMAPE | 對稱百分比誤差 | 序列有 0 時不穩，只當參考 |
| coverage_80／95 | 實際值落在 80%／95% 區間的比例 | 理想值 0.80／0.95；太低代表區間太窄 |
| width_80／95 | 區間平均寬度 | 涵蓋率差不多時，越窄越好 |
| WQL | 0.1／0.5／0.9 分位數的加權分位數損失 | 越低越好，**用來選模型** |
| WQL_skill_vs_snaive | 1 − 模型 WQL ÷ 季節 Naive 的 WQL | > 0 代表贏過最簡單的方法 |

## 選模與輸出

1. 依 WQL 排序，平手時比 MASE。只有能產生 80% 區間的模型才列入選擇。
2. 用全部資料重新訓練選中的模型，輸出未來 `horizon` 期的區間。
3. 家數、人數這類序列，下界截在 0；整數序列的下界往下取整、上界往上取整，讓區間更保守。
4. 遇到以下情況會自動在報告加上警示：80% 涵蓋率低於 65% 或高於 95%、所選模型沒贏過季節 Naive、回測起點少於 10 個、輸入序列本身是推估值。

輸出檔案（`reports/forecast/`）

| 檔案 | 用途 |
|---|---|
| `{id}_forecast.json` | **對外**：序列出處、回測排行、選中的模型與理由、各期 80%／95% 區間、警示 |
| `{id}_leaderboard.csv` | 各模型回測指標 |
| `{id}_error_by_horizon.csv` | 各模型在每個預測步數的誤差，用來回答「預測三年後準不準」 |
| `{id}_backtest_detail.csv` | 每個起點、每一期的預測與實際值 |
| `{id}_quantiles_internal.csv` | 內部用：完整分位數，不對外顯示 |

## PR #5 真實資料基線

```bash
python -m forecast.run_real --series jobmarket --horizon 12 --step 3
python -m forecast.run_real --series gcis --horizon 12 --step 3
python -m forecast.run_real --series gcis --horizon 12 --step 3 --chronos
python -m forecast.run_real --series jobmarket --horizon 12 --step 3 --chronos
```

`--chronos` 只在三個相同的統計基線上加入 Chronos-Bolt，使用**同一批回測起點**比較；預設模型為 `amazon/chronos-bolt-tiny`，可用 `--chronos-model-id` 指定其他模型。需先安裝 `chronos-forecasting`（含 PyTorch），首次執行會下載權重。若套件或權重不可用，不能宣稱已完成 Chronos 的誤差比較。

| 序列 | 實際可用段 | 回測設定 | 模型 | MAE | RMSE | 80% 實際涵蓋率 | WQL |
|---|---|---|---|---:|---:|---:|---:|
| 公立就業服務系統新登記求才人數 | 2022-01～2026-06，54 個月 | 12 個月、每 3 個月起算、6 個起點 | **季節 Naive（選中）** | 917.537 人 | 1169.025 人 | 98.15% | 0.0734 |
| 同上 | 同上 | 同上 | Chronos-Bolt-tiny | 1541.2252 人 | 1832.0424 人 | 87.04% | 0.1044 |
| 製造業新設公司家數，官方缺月已補回 | 2012-06～2026-08，171 個月 | 12 個月、每 3 個月起算、45 個起點 | **Chronos-Bolt-tiny（選中）** | 24.147 家 | 31.4247 家 | 80.65% | 0.1429 |
| 同上 | 同上 | 同上 | 季節 Naive | 27.8889 家 | 38.407 家 | 78.54% | 0.1760 |

以上是重疊預測期的 rolling-origin 回測誤差，不是未來誤差保證。就業通序列的 80% 區間涵蓋率明顯高於名目 80%，區間偏寬，且只有 6 個回測起點；應同時看 `error_by_horizon.csv`，不能只看平均。Chronos 在就業通序列沒有勝過季節 Naive，因此**不會因為模型較新就選它**。每個模型的完整指標與每個起點的結果見 `reports/forecast_real/`。

就業通資料僅代表公立就業服務系統，不是台中所有職缺，也無法拆成特定區域與產業；資料目前截至 2026-06，輸出以該月為起點。GCIS 新設序列已補回官方八、九月觀測值，現在截止 2026-08；預測期為 2026-09～2027-08，截止日後已過去的月份仍屬該起點預測，不應當成最新實績。對外 JSON 只提供每期區間；Chronos-Bolt 不支援的 95% 區間標成 `null`。

## 官方缺月修復

共補回 **147 筆觀測值**：2014-11 的 21 筆現有公司統計，以及 2025-08、09 各 63 筆新設、解散與現有公司統計。八、九月台中製造業新設公司分別為 **91 家、75 家**。數值來自經濟部統計處官方公司登記月報，不做插值、不填 0；標記 `official_monthly_recovered`。

官方工作簿位於 `data/raw/moea_company_monthly/`。解析時驗證月份、單位、台中市兩段表格、21 個行業欄位、非負整數家數、各行業家數及資本額合計。另將七月、十月各 63 筆，以及 2014-11 未缺的新設／解散 42 筆與原 GCIS 數值核對，家數及資本額完全相符。來源 URL 與 SHA-256 記錄在 `reports/forecast_real/gcis_recovery_audit.json`。

```bash
pip install pandas numpy xlrd openpyxl requests
python -m etl.recover_gcis_months
python -m forecast.run_real --series gcis --chronos --horizon 12 --step 3
```

修復程式可重跑，不覆寫相矛盾的既有觀測值；主 ETL 也會讀取已下載月報作備援。來源的部分行業名稱改為「營建工程業」「出版影音及資通訊業」「教育業」，使用別名銜接既有欄位；這不代表所有行業的跨期分類完全不變，長期比較仍須留意分類調整。

## 通用 CSV 執行

```bash
python -m forecast.run --csv data/processed/某序列.csv --id tc_mfg_new --name "臺中製造業新設家數" --freq M --horizon 36 --step 3 --source "經濟部商工登記 公司設立登記清冊（月份）"
```

CSV 需要 `period`、`value` 兩欄，期別要連續；缺期須先回到原始來源查證，不能自行補 0，引擎會拒收不連續的序列。

加上 `--chronos` 可以把 Chronos 一起比較，但需要先安裝 `chronos-forecasting` 和 `torch`。第一次執行會從 Hugging Face 下載模型（chronos-bolt-small 約 190 MB）。

## 尚未接入回測的序列

| 序列 | 頻率 | 長度 | 預測期 | 來源（見 DATA_CATALOG） |
|---|---|---|---|---|
| 臺中各區 × 中類工廠家數 | 月 | 2024-08 起，約 18 期 | 太短，只做描述不做預測 | C1 |
| 臺中製造業勞保投保人數 | 年 | 107–114 年，8 期 | 太短，只當控制總數 | B1 |
