"""
預測報告：回測所有模型 → 選模 → 用全部資料重新訓練 → 輸出預測區間

對外（public JSON）只有區間，沒有單一數字；完整分位數另存 internal CSV，給數值驗證器與內部檢查用。
選模依 WQL（區間品質），平手看 MASE；並和季節 Naive 比較，算出「比最簡單方法好多少」。
"""
import json
import math
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from forecast.backtest import (INTERVALS, QUANTILES, default_min_train, qcol, run_backtests, score,
                               score_by_horizon)
from forecast.models import ModelFactory, default_models, postprocess
from forecast.series import Series

DISCLAIMER = ("本預測為依歷史資料推算的可能範圍，不是保證值。80%／95% 是名目區間；"
              "實際涵蓋率請看回測 coverage_80／coverage_95，可能與名目值不同。")


def _round_range(lo: float, hi: float, integer: bool):
    if np.isnan(lo) or np.isnan(hi):
        return None
    if integer:   # 家數、人數：下界取整往下、上界往上，區間只會更保守
        return [int(math.floor(lo)), int(math.ceil(hi))]
    return [round(float(lo), 4), round(float(hi), 4)]


def build_leaderboard(bt: pd.DataFrame) -> pd.DataFrame:
    rows = [{"model": name, **score(g)} for name, g in bt.groupby("model", sort=False)]
    lb = pd.DataFrame(rows)
    base = lb.loc[lb["model"] == "snaive", "WQL"]
    base_wql = float(base.iloc[0]) if len(base) and pd.notna(base.iloc[0]) else None
    lb["WQL_skill_vs_snaive"] = lb["WQL"].apply(lambda w: None if base_wql in (None, 0) or pd.isna(w) else 1 - w / base_wql)
    lb = lb.sort_values(["WQL", "MASE"], na_position="last").reset_index(drop=True)
    lb.insert(0, "rank", range(1, len(lb) + 1))
    return lb


def _warnings(series: Series, chosen: dict, n_origins: int) -> List[str]:
    out = []
    cov = chosen.get("coverage_80")
    if cov is not None and cov < 0.65:
        out.append(f"回測 80% 區間實際涵蓋率只有 {cov:.0%}，區間可能偏窄，解讀時要保守。")
    if cov is not None and cov > 0.95:
        out.append(f"回測 80% 區間實際涵蓋率 {cov:.0%}，區間偏寬，資訊量有限。")
    skill = chosen.get("WQL_skill_vs_snaive")
    if skill is not None and skill <= 0 and chosen["model"] != "snaive":
        out.append("所選模型沒有贏過「延續去年同期」的簡單方法。")
    if n_origins < 10:
        out.append(f"回測只有 {n_origins} 個起點，誤差數字的不確定性高。")
    if series.is_estimate:
        out.append("輸入序列本身是推估值，預測區間沒有包含推估誤差。")
    return out


def run_forecast(series: Series, horizon: int, factories: Optional[List[ModelFactory]] = None,
                 skipped: Optional[dict] = None, min_train: int = None, step: int = 1,
                 include_chronos: bool = False, out_dir: Optional[Path] = None) -> dict:
    if factories is None:
        factories, skipped = default_models(include_chronos=include_chronos)
    skipped = skipped or {}
    min_train = min_train or default_min_train(series)

    bt = run_backtests(series, factories, horizon, min_train, step)
    lb = build_leaderboard(bt)
    usable = lb[lb["WQL"].notna() & lb["coverage_80"].notna()]
    if usable.empty:
        raise RuntimeError("沒有任何模型完成回測")
    chosen = usable.iloc[0].to_dict()

    factory = next(f for f in factories if f().name == chosen["model"])
    model = factory().fit(series.values, season_length=series.season_length)
    q = postprocess(model.predict_quantiles(horizon, QUANTILES), series.nonnegative)
    future = series.future_periods(horizon)
    integer = series.nonnegative and np.allclose(series.values, np.round(series.values))

    forecast = []
    for i, p in enumerate(future):
        item = {"period": str(p)}
        for level, (lo_q, hi_q) in INTERVALS.items():
            item[f"range_{level}"] = _round_range(q[i, QUANTILES.index(lo_q)], q[i, QUANTILES.index(hi_q)], integer)
        forecast.append(item)

    n_origins = int(bt["origin"].nunique())   # 所有模型共用同一組起點
    clean = lambda v: None if (isinstance(v, float) and math.isnan(v)) else (round(v, 4) if isinstance(v, float) else v)
    result = {
        "series": {"id": series.series_id, "name": series.name, "unit": series.unit, "freq": series.freq,
                   "first_period": str(series.periods[0]), "last_period": str(series.periods[-1]),
                   "n_obs": len(series), "sources": series.sources, "is_estimate": series.is_estimate},
        "backtest": {"method": "rolling-origin（expanding window）", "horizon": horizon, "min_train": min_train,
                     "step": step, "n_origins": n_origins,
                     "leaderboard": [{k: clean(v) for k, v in r.items()} for r in lb.to_dict("records")],
                     "skipped_models": skipped},
        "selected_model": {"name": chosen["model"], "description": model.describe(),
                           "reason": "回測 WQL 最低（區間品質最好）" + ("，平手時比 MASE" if len(usable) > 1 else "")},
        "forecast": forecast,
        "warnings": _warnings(series, chosen, n_origins),
        "disclaimer": DISCLAIMER,
    }

    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        sid = series.series_id
        (out_dir / f"{sid}_forecast.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        lb.to_csv(out_dir / f"{sid}_leaderboard.csv", index=False, encoding="utf-8-sig")
        pd.concat([score_by_horizon(g) for _, g in bt.groupby("model", sort=False)]).to_csv(
            out_dir / f"{sid}_error_by_horizon.csv", index=False, encoding="utf-8-sig")
        bt.to_csv(out_dir / f"{sid}_backtest_detail.csv", index=False, encoding="utf-8-sig")
        internal = pd.DataFrame(q, columns=[qcol(x) for x in QUANTILES])
        internal.insert(0, "period", [str(p) for p in future])
        internal.to_csv(out_dir / f"{sid}_quantiles_internal.csv", index=False, encoding="utf-8-sig")
    return result
