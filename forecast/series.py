"""
時間序列資料結構
每條序列都帶著出處（sources）與是否為推估值（is_estimate），讓預測結果可以追溯到原始資料（P4）。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

# 頻率 → 預設季節長度
SEASON_LENGTH = {"M": 12, "Q": 4, "Y": 1}


@dataclass
class Series:
    series_id: str
    name: str
    periods: pd.PeriodIndex
    values: np.ndarray
    unit: str = ""
    sources: List[str] = field(default_factory=list)
    nonnegative: bool = True      # 家數、人數不可能是負的，預測下界截在 0
    is_estimate: bool = False     # 序列本身是推估值（例如各區中類就業人數）

    def __post_init__(self):
        self.values = np.asarray(self.values, dtype=float)
        if len(self.values) != len(self.periods):
            raise ValueError("periods 與 values 長度不同")
        if np.isnan(self.values).any():
            raise ValueError(f"{self.series_id} 有缺值，請先在 ETL 處理")
        if not self.periods.is_monotonic_increasing or self.periods.has_duplicates:
            raise ValueError(f"{self.series_id} 期別未排序或重複")
        expected = pd.period_range(self.periods[0], self.periods[-1], freq=self.periods.freq)
        if len(expected) != len(self.periods):
            raise ValueError(f"{self.series_id} 期別不連續（缺 {len(expected) - len(self.periods)} 期），請先在 ETL 補齊或標記")

    @property
    def freq(self) -> str:
        return self.periods.freqstr[0]

    @property
    def season_length(self) -> int:
        return SEASON_LENGTH.get(self.freq, 1)

    def __len__(self):
        return len(self.values)

    def future_periods(self, horizon: int) -> pd.PeriodIndex:
        return pd.period_range(self.periods[-1] + 1, periods=horizon, freq=self.periods.freq)

    @classmethod
    def from_csv(cls, path, series_id: str, name: str, freq: str, period_col="period", value_col="value", **kw):
        df = pd.read_csv(Path(path))
        periods = pd.PeriodIndex(df[period_col].astype(str), freq=freq)
        order = np.argsort(periods)
        return cls(series_id=series_id, name=name, periods=periods[order], values=df[value_col].to_numpy()[order], **kw)
