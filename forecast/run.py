"""
命令列執行：
python -m forecast.run --csv data/processed/xxx.csv --id tc_mfg_new --name "臺中製造業新設家數" --freq M --horizon 36
CSV 需有 period、value 兩欄（period 例：2024-01、2024Q1、2024）。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import REPORT_DIR
from forecast.report import run_forecast
from forecast.series import Series


def main():
    ap = argparse.ArgumentParser(description="回測統計基線與時序模型，輸出預測區間")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--freq", required=True, choices=["M", "Q", "Y"])
    ap.add_argument("--horizon", type=int, required=True)
    ap.add_argument("--unit", default="")
    ap.add_argument("--source", action="append", default=[], help="資料出處，可重複")
    ap.add_argument("--min-train", type=int, default=None)
    ap.add_argument("--step", type=int, default=1, help="回測起點間隔，資料長時調大可加速")
    ap.add_argument("--chronos", action="store_true", help="加入 Chronos（需 chronos-forecasting、torch）")
    ap.add_argument("--estimate", action="store_true", help="輸入序列本身是推估值")
    args = ap.parse_args()

    series = Series.from_csv(args.csv, args.id, args.name, args.freq, unit=args.unit,
                             sources=args.source, is_estimate=args.estimate)
    out_dir = REPORT_DIR / "forecast"
    result = run_forecast(series, args.horizon, min_train=args.min_train, step=args.step,
                          include_chronos=args.chronos, out_dir=out_dir)
    print(json.dumps({k: result[k] for k in ("selected_model", "warnings")}, ensure_ascii=False, indent=2))
    print(f"輸出：{out_dir}")


if __name__ == "__main__":
    main()
