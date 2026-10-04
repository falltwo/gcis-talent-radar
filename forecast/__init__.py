"""
預測引擎（Step 3）
- series.py    時間序列與資料出處
- models.py    統計基線（Naive / 季節 Naive / Drift / ETS / ARIMA）與 Chronos 接口，全部輸出分位數
- backtest.py  rolling-origin 回測與誤差指標
- report.py    比較模型、選模、輸出預測區間（對外不給單一數字）
"""
