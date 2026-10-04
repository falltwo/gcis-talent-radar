"""
預測引擎測試：python -m pytest tests/test_forecast.py -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forecast.backtest import QUANTILES, qcol, rolling_origin, score
from forecast.models import Drift, Forecaster, Naive, SeasonalNaive, postprocess
from forecast.report import run_forecast
from forecast.series import Series


def monthly(values, start="2013-01", **kw):
    periods = pd.period_range(start, periods=len(values), freq="M")
    return Series("test", "測試序列", periods, np.asarray(values, float), **kw)


class Spy(Forecaster):
    """記錄每次 fit 拿到的訓練資料"""
    name = "spy"
    seen = []

    def fit(self, y, season_length=1):
        Spy.seen.append(np.array(y))
        self.last = y[-1]
        return self

    def predict_quantiles(self, horizon, quantiles):
        return np.full((horizon, len(quantiles)), self.last)


def test_backtest_trains_only_on_past():
    Spy.seen = []
    y = np.arange(40, dtype=float)              # 值 = 位置，方便檢查有沒有偷看未來
    bt = rolling_origin(monthly(y), Spy, horizon=6, min_train=24)
    assert len(Spy.seen) == 40 - 24
    for k, train in enumerate(Spy.seen):
        t = 24 + k
        assert len(train) == t and train.max() == t - 1
    first = bt[bt["origin"] == "2014-12"]       # 第 24 期是 2014-12
    assert first["period"].iloc[0] == "2015-01" and first["actual"].iloc[0] == 24


def test_seasonal_naive_exact_on_pure_seasonality():
    y = np.tile(np.arange(1, 13, dtype=float) * 10, 6)
    bt = rolling_origin(monthly(y), SeasonalNaive, horizon=12, min_train=24)
    assert score(bt)["MAE"] == pytest.approx(0.0)


def test_quantiles_sorted_and_nonnegative():
    rng = np.random.default_rng(0)
    y = np.abs(np.cumsum(rng.normal(0, 3, 60))) + 1
    q = postprocess(Drift().fit(y).predict_quantiles(24, QUANTILES), nonnegative=True)
    assert (np.diff(q, axis=1) >= 0).all()
    assert (q >= 0).all()


def test_interval_coverage_is_calibrated_on_random_walk():
    rng = np.random.default_rng(1)
    y = 1000 + np.cumsum(rng.normal(0, 5, 400))
    s = score(rolling_origin(monthly(y, nonnegative=False), Naive, horizon=1, min_train=30))
    assert 0.72 <= s["coverage_80"] <= 0.88
    assert 0.90 <= s["coverage_95"] <= 0.99


def test_unsupported_quantiles_are_not_scored():
    class Only80(Naive):
        name = "only80"
        quantile_range = (0.1, 0.9)

        def predict_quantiles(self, horizon, quantiles):
            out = super().predict_quantiles(horizon, quantiles)
            out[:, [i for i, q in enumerate(quantiles) if not 0.1 <= q <= 0.9]] = np.nan
            return out

    rng = np.random.default_rng(2)
    s = score(rolling_origin(monthly(100 + np.cumsum(rng.normal(0, 1, 60))), Only80, horizon=3, min_train=24))
    assert s["coverage_95"] is None and s["coverage_80"] is not None and s["WQL"] is not None


def test_public_forecast_has_ranges_only(tmp_path):
    rng = np.random.default_rng(3)
    season = np.tile([5, 3, 8, 10, 12, 9, 7, 6, 11, 13, 9, 4], 8)
    y = np.round(200 + season * 3 + np.arange(96) * 0.5 + rng.normal(0, 4, 96))
    s = monthly(y, sources=["測試資料"])
    result = run_forecast(s, horizon=12, factories=[Naive, SeasonalNaive, Drift], step=3, out_dir=tmp_path)
    assert len(result["forecast"]) == 12
    for item in result["forecast"]:
        assert set(item) == {"period", "range_80", "range_95"}
        lo80, hi80 = item["range_80"]
        lo95, hi95 = item["range_95"]
        assert lo95 <= lo80 <= hi80 <= hi95
        assert all(isinstance(v, int) for v in (lo80, hi80, lo95, hi95))   # 整數序列 → 整數區間
    assert result["series"]["sources"] == ["測試資料"]
    assert (tmp_path / "test_quantiles_internal.csv").exists()


def test_series_rejects_gaps():
    periods = pd.PeriodIndex(["2024-01", "2024-02", "2024-04"], freq="M")
    with pytest.raises(ValueError):
        Series("gap", "缺期", periods, [1, 2, 3])


def test_statsmodels_models_run():
    pytest.importorskip("statsmodels")
    from forecast.models import ARIMA, ETS
    rng = np.random.default_rng(4)
    y = 300 + np.tile([0, 5, 10, 5, 0, -5, -10, -5, 0, 5, 10, 5], 6) + np.arange(72) + rng.normal(0, 2, 72)
    for cls in (ETS, ARIMA):
        q = cls().fit(y, season_length=12).predict_quantiles(12, QUANTILES)
        assert q.shape == (12, len(QUANTILES)) and np.isfinite(q).all()
        assert (np.diff(q, axis=1) >= -1e-9).all()
