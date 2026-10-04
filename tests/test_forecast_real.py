"""Focused tests for official-series selection and the optional Chronos adapter."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forecast.models import Chronos, Drift, Naive, SeasonalNaive
from forecast.real_data import load_gcis_mfg_new_pre_gap, load_jobmarket_openings
from forecast.report import run_forecast


class ForecastRealTest(unittest.TestCase):
    def test_gcis_stops_before_missing_months(self):
        series = load_gcis_mfg_new_pre_gap()
        self.assertEqual(str(series.periods[-1]), "2025-07")
        self.assertEqual(len(series), 158)

    def test_jobmarket_uses_one_scope_and_monthly_rows(self):
        series = load_jobmarket_openings()
        self.assertEqual(str(series.periods[0]), "2022-01")
        self.assertEqual(str(series.periods[-1]), "2026-06")
        self.assertEqual(len(series), 54)

    def test_public_output_has_intervals_and_error_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run_forecast(load_jobmarket_openings(), horizon=6,
                                  factories=[Naive, SeasonalNaive, Drift], step=3,
                                  out_dir=Path(folder))
            public = json.loads((Path(folder) / "tc_jobmarket_openings_forecast.json").read_text(encoding="utf-8"))
            self.assertEqual(len(public["forecast"]), 6)
            self.assertEqual(set(public["forecast"][0]), {"period", "range_80", "range_95"})
            self.assertIsInstance(result["backtest"]["leaderboard"][0]["MAE"], float)

    def test_chronos_passes_inputs_and_keeps_95_percent_unavailable(self):
        calls = []

        class FakeTensor:
            def __init__(self, data):
                self.data = np.asarray(data)
            def __getitem__(self, key):
                return FakeTensor(self.data[key])
            def cpu(self):
                return self
            def numpy(self):
                return self.data

        class FakePipeline:
            def predict_quantiles(self, **kwargs):
                calls.append(kwargs)
                h = kwargs["prediction_length"]
                q = kwargs["quantile_levels"]
                return FakeTensor(np.ones((1, h, len(q))) * 12), None

        fake_torch = types.SimpleNamespace(float32="float32", tensor=lambda y, dtype: FakeTensor(y))
        with patch.dict(sys.modules, {"torch": fake_torch}):
            with patch.object(Chronos, "_pipeline", return_value=FakePipeline()):
                result = Chronos().fit([9, 10, 11]).predict_quantiles(2, (0.025, 0.1, 0.5, 0.9, 0.975))
        self.assertEqual(len(calls), 1)
        self.assertIn("inputs", calls[0])
        self.assertNotIn("context", calls[0])
        self.assertTrue(np.isnan(result[:, [0, 4]]).all())
        self.assertTrue(np.isfinite(result[:, 1:4]).all())


if __name__ == "__main__":
    unittest.main()
