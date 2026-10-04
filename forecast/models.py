"""
預測模型：一律輸出分位數，不輸出單一數字
- 統計基線（只需 numpy）：Naive、季節 Naive、Drift，區間用常態近似（Hyndman & Athanasopoulos, FPP3 §5.5）
- 統計模型（需 statsmodels）：ETS（AIC 選型、模擬取分位數）、ARIMA（KPSS 定差分、AIC 選階）
- 時序基礎模型（需 chronos-forecasting + torch）：Chronos-Bolt，zero-shot，只看訓練期資料

每個模型 fit() 只拿到預測起點以前的資料；回測的防洩漏由 backtest.py 保證。
"""
import warnings
from statistics import NormalDist
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

_Z = NormalDist()


def _normal_quantiles(point: np.ndarray, sigma_h: np.ndarray, quantiles: Sequence[float]) -> np.ndarray:
    z = np.array([_Z.inv_cdf(q) for q in quantiles])
    return point[:, None] + sigma_h[:, None] * z[None, :]


def _rmse(resid: np.ndarray) -> float:
    resid = resid[~np.isnan(resid)]
    return float(np.sqrt(np.mean(resid ** 2))) if len(resid) else 0.0


class Forecaster:
    name = "base"
    label = "基底"
    # 模型能可靠輸出的分位數範圍；範圍外回傳 NaN，回測時該區間記為「不適用」
    quantile_range: Tuple[float, float] = (0.0, 1.0)

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return True, ""

    def fit(self, y: np.ndarray, season_length: int = 1) -> "Forecaster":
        raise NotImplementedError

    def predict_quantiles(self, horizon: int, quantiles: Sequence[float]) -> np.ndarray:
        """回傳 shape = (horizon, len(quantiles))"""
        raise NotImplementedError

    def describe(self) -> str:
        return self.label


# ---------------------------------------------------------------- 統計基線（numpy）

class Naive(Forecaster):
    name, label = "naive", "Naive（延續最後一期）"

    def fit(self, y, season_length=1):
        self.y = np.asarray(y, float)
        self.sigma = _rmse(np.diff(self.y))
        return self

    def predict_quantiles(self, horizon, quantiles):
        h = np.arange(1, horizon + 1)
        point = np.full(horizon, self.y[-1])
        return _normal_quantiles(point, self.sigma * np.sqrt(h), quantiles)


class SeasonalNaive(Forecaster):
    name, label = "snaive", "季節 Naive（延續去年同期）"

    def fit(self, y, season_length=1):
        self.y = np.asarray(y, float)
        self.m = season_length if season_length > 1 and len(self.y) > season_length else 1
        self.sigma = _rmse(self.y[self.m:] - self.y[:-self.m])
        return self

    def predict_quantiles(self, horizon, quantiles):
        h = np.arange(1, horizon + 1)
        last_season = self.y[-self.m:]
        point = last_season[(h - 1) % self.m]
        k = (h - 1) // self.m
        return _normal_quantiles(point, self.sigma * np.sqrt(k + 1), quantiles)


class Drift(Forecaster):
    name, label = "drift", "Drift（延續歷史平均變化）"

    def fit(self, y, season_length=1):
        self.y = np.asarray(y, float)
        n = len(self.y)
        self.slope = (self.y[-1] - self.y[0]) / (n - 1) if n > 1 else 0.0
        self.sigma = _rmse(np.diff(self.y) - self.slope)
        return self

    def predict_quantiles(self, horizon, quantiles):
        h = np.arange(1, horizon + 1)
        n = len(self.y)
        point = self.y[-1] + h * self.slope
        return _normal_quantiles(point, self.sigma * np.sqrt(h * (1 + h / max(n - 1, 1))), quantiles)


# ---------------------------------------------------------------- 統計模型（statsmodels）

def _statsmodels_available() -> Tuple[bool, str]:
    try:
        import statsmodels  # noqa: F401
        return True, ""
    except ImportError:
        return False, "未安裝 statsmodels"


class ETS(Forecaster):
    """誤差、趨勢、季節皆為加法；在 {無趨勢, 阻尼趨勢} × {無季節, 季節} 中以 AIC 選型"""
    name, label = "ets", "ETS（指數平滑，AIC 選型）"
    n_sims = 2000

    @classmethod
    def available(cls):
        return _statsmodels_available()

    def fit(self, y, season_length=1):
        from statsmodels.tsa.exponential_smoothing.ets import ETSModel

        y = np.asarray(y, float)
        seasonal_ok = season_length > 1 and len(y) >= 2 * season_length + 2
        best = None
        for trend in (None, "add"):
            for seasonal in ((None, "add") if seasonal_ok else (None,)):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    try:
                        res = ETSModel(y, error="add", trend=trend, damped_trend=trend is not None,
                                       seasonal=seasonal, seasonal_periods=season_length if seasonal else None
                                       ).fit(disp=False, maxiter=200)
                    except Exception:
                        continue
                if np.isfinite(res.aic) and (best is None or res.aic < best[0]):
                    best = (res.aic, res, trend, seasonal)
        if best is None:
            raise RuntimeError("ETS 所有型態都無法估計")
        _, self.res, trend, seasonal = best
        self.spec = f"ETS(A,{'Ad' if trend else 'N'},{'A' if seasonal else 'N'})"
        return self

    def predict_quantiles(self, horizon, quantiles):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            kw = dict(nsimulations=horizon, repetitions=self.n_sims, anchor="end")
            try:    # statsmodels ≥ 0.15 用 rng，舊版用 random_state；固定種子讓結果可重現
                sims = self.res.simulate(**kw, rng=np.random.default_rng(0))
            except TypeError:
                sims = self.res.simulate(**kw, random_state=0)
        sims = np.asarray(sims).reshape(horizon, -1)
        return np.quantile(sims, quantiles, axis=1).T

    def describe(self):
        return f"{self.label}：{getattr(self, 'spec', '')}"


class ARIMA(Forecaster):
    """KPSS 檢定決定是否一階差分，p, q ∈ {0,1,2} 以 AIC 選階；區間為常態近似"""
    name, label = "arima", "ARIMA（KPSS 定差分、AIC 選階）"

    @classmethod
    def available(cls):
        return _statsmodels_available()

    def fit(self, y, season_length=1):
        from statsmodels.tsa.arima.model import ARIMA as SMARIMA
        from statsmodels.tsa.stattools import kpss

        y = np.asarray(y, float)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                d = 1 if kpss(y, regression="c", nlags="auto")[1] < 0.05 else 0
            except Exception:
                d = 1
            best = None
            for p in range(3):
                for q in range(3):
                    try:
                        res = SMARIMA(y, order=(p, d, q), trend="t" if d == 1 else "c").fit()
                    except Exception:
                        continue
                    if np.isfinite(res.aic) and (best is None or res.aic < best[0]):
                        best = (res.aic, res, (p, d, q))
        if best is None:
            raise RuntimeError("ARIMA 所有階數都無法估計")
        _, self.res, self.order = best
        return self

    def predict_quantiles(self, horizon, quantiles):
        fc = self.res.get_forecast(horizon)
        return _normal_quantiles(np.asarray(fc.predicted_mean), np.asarray(fc.se_mean), quantiles)

    def describe(self):
        return f"{self.label}：ARIMA{getattr(self, 'order', '')}"


# ---------------------------------------------------------------- 時序基礎模型（Chronos）

class Chronos(Forecaster):
    """
    Amazon Chronos-Bolt，zero-shot（不用本地資料訓練），context 只放訓練期資料。
    Chronos-Bolt 只學過 0.1–0.9 分位數，所以 95% 區間不適用，回測只評 80% 區間。
    """
    name = "chronos"
    quantile_range = (0.1, 0.9)
    _pipelines: Dict[str, object] = {}

    def __init__(self, model_id: str = "amazon/chronos-bolt-small", device: str = "cpu"):
        self.model_id = model_id
        self.device = device
        self.label = f"Chronos（{model_id}，zero-shot）"

    @classmethod
    def available(cls):
        try:
            import chronos  # noqa: F401
            import torch  # noqa: F401
            return True, ""
        except ImportError:
            return False, "未安裝 chronos-forecasting / torch"

    def _pipeline(self):
        if self.model_id not in self._pipelines:
            import torch
            from chronos import BaseChronosPipeline
            self._pipelines[self.model_id] = BaseChronosPipeline.from_pretrained(
                self.model_id, device_map=self.device, torch_dtype=torch.float32)
        return self._pipelines[self.model_id]

    def fit(self, y, season_length=1):
        self.y = np.asarray(y, float)
        return self

    def predict_quantiles(self, horizon, quantiles):
        import torch

        lo, hi = self.quantile_range
        inside = [q for q in quantiles if lo <= q <= hi]
        qs, _ = self._pipeline().predict_quantiles(
            context=torch.tensor(self.y, dtype=torch.float32), prediction_length=horizon, quantile_levels=inside)
        qs = qs[0].cpu().numpy()  # (horizon, len(inside))
        out = np.full((horizon, len(quantiles)), np.nan)
        for j, q in enumerate(quantiles):
            if q in inside:
                out[:, j] = qs[:, inside.index(q)]
        return out


# ---------------------------------------------------------------- 模型清單

ModelFactory = Callable[[], Forecaster]


def default_models(include_chronos: bool = False, chronos_model_id: str = "amazon/chronos-bolt-small"
                   ) -> Tuple[List[ModelFactory], Dict[str, str]]:
    """回傳 (可用模型的建構函式, 被略過的模型與原因)"""
    candidates: List[Tuple[type, ModelFactory]] = [
        (Naive, Naive), (SeasonalNaive, SeasonalNaive), (Drift, Drift), (ETS, ETS), (ARIMA, ARIMA)]
    if include_chronos:
        candidates.append((Chronos, lambda: Chronos(chronos_model_id)))
    factories, skipped = [], {}
    for cls, factory in candidates:
        ok, reason = cls.available()
        if ok:
            factories.append(factory)
        else:
            skipped[cls.name] = reason
    return factories, skipped


def postprocess(q: np.ndarray, nonnegative: bool) -> np.ndarray:
    """分位數排序（避免交叉），家數、人數截在 0；NaN 保留"""
    out = q.copy()
    for i in range(out.shape[0]):
        row = out[i]
        mask = ~np.isnan(row)
        row[mask] = np.sort(row[mask])
    if nonnegative:
        out = np.where(np.isnan(out), out, np.maximum(out, 0.0))
    return out
