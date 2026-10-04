"""
Rolling-origin 回測（expanding window）
- 每個預測起點 t 只用 y[:t] 訓練，預測 t 之後 horizon 期，再跟實際值比
- 所有模型用同一組起點，指標才能比較

指標
- 點誤差（用中位數 q0.5）：MAE、RMSE、MASE、sMAPE
- 區間：80%／95% 涵蓋率（理想值 0.80／0.95）、平均寬度
- WQL：0.1/0.5/0.9 三個分位數的加權分位數損失，Chronos 也能比，用來選模型
"""
from typing import List, Sequence

import numpy as np
import pandas as pd

from forecast.models import Forecaster, ModelFactory, postprocess
from forecast.series import Series

QUANTILES = (0.025, 0.1, 0.5, 0.9, 0.975)
INTERVALS = {80: (0.1, 0.9), 95: (0.025, 0.975)}
WQL_QUANTILES = (0.1, 0.5, 0.9)


def qcol(q: float) -> str:
    return f"q{q:g}"


def default_min_train(series: Series) -> int:
    return max(3 * series.season_length, 12)


def rolling_origin(series: Series, factory: ModelFactory, horizon: int, min_train: int = None,
                   step: int = 1, quantiles: Sequence[float] = QUANTILES) -> pd.DataFrame:
    y, m = series.values, series.season_length
    min_train = min_train or default_min_train(series)
    if len(y) <= min_train:
        raise ValueError(f"{series.series_id} 只有 {len(y)} 期，不足以回測（至少要 {min_train + 1} 期）")

    rows = []
    for t in range(min_train, len(y), step):
        train = y[:t]                       # 只用起點以前的資料
        h = min(horizon, len(y) - t)
        model: Forecaster = factory()
        try:
            model.fit(train, season_length=m)
            q = postprocess(model.predict_quantiles(h, quantiles), series.nonnegative)
            error = ""
        except Exception as exc:
            q = np.full((h, len(quantiles)), np.nan)
            error = f"{type(exc).__name__}: {exc}"[:200]
        # MASE 分母：該起點訓練期的季節 Naive 一步誤差
        lag = m if len(train) > m else 1
        scale = float(np.mean(np.abs(train[lag:] - train[:-lag]))) if len(train) > lag else np.nan
        for i in range(h):
            row = {"model": model.name, "origin": str(series.periods[t - 1]), "h": i + 1,
                   "period": str(series.periods[t + i]), "actual": y[t + i], "mase_scale": scale, "error": error}
            row.update({qcol(qq): q[i, j] for j, qq in enumerate(quantiles)})
            rows.append(row)
    return pd.DataFrame(rows)


def _pinball(actual: np.ndarray, pred: np.ndarray, q: float) -> np.ndarray:
    diff = actual - pred
    return np.maximum(q * diff, (q - 1) * diff)


def score(bt: pd.DataFrame) -> dict:
    """單一模型的回測結果 → 指標"""
    ok = bt[bt["error"] == ""]
    out = {"n_forecasts": int(len(ok)), "n_failed_origins": int(bt.loc[bt["error"] != "", "origin"].nunique())}
    if ok.empty:
        return out
    a, med = ok["actual"].to_numpy(), ok[qcol(0.5)].to_numpy()
    e = a - med
    out["MAE"] = float(np.mean(np.abs(e)))
    out["RMSE"] = float(np.sqrt(np.mean(e ** 2)))
    scale = ok["mase_scale"].to_numpy()
    valid = scale > 0
    out["MASE"] = float(np.mean(np.abs(e[valid]) / scale[valid])) if valid.any() else None
    denom = np.abs(a) + np.abs(med)
    nz = denom > 0
    out["sMAPE_pct"] = float(np.mean(200 * np.abs(e[nz]) / denom[nz])) if nz.any() else None

    for level, (lo_q, hi_q) in INTERVALS.items():
        lo, hi = ok[qcol(lo_q)].to_numpy(), ok[qcol(hi_q)].to_numpy()
        if np.isnan(lo).all() or np.isnan(hi).all():
            out[f"coverage_{level}"] = None   # 模型不支援這個區間（例如 Chronos 的 95%）
            out[f"width_{level}"] = None
            continue
        out[f"coverage_{level}"] = float(np.mean((a >= lo) & (a <= hi)))
        out[f"width_{level}"] = float(np.mean(hi - lo))

    total = np.sum(np.abs(a))
    losses = [2 * np.sum(_pinball(a, ok[qcol(q)].to_numpy(), q)) / total for q in WQL_QUANTILES] if total > 0 else []
    out["WQL"] = float(np.mean(losses)) if losses and not np.isnan(losses).any() else None
    return out


def score_by_horizon(bt: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{"model": bt["model"].iloc[0], "h": h, **score(g)} for h, g in bt.groupby("h")])


def run_backtests(series: Series, factories: List[ModelFactory], horizon: int, min_train: int = None,
                  step: int = 1) -> pd.DataFrame:
    return pd.concat([rolling_origin(series, f, horizon, min_train, step) for f in factories], ignore_index=True)
