"""Run comparable baseline backtests on the validated processed series.

python -m forecast.run_real --series jobmarket --horizon 12 --step 3
python -m forecast.run_real --series jobmarket --chronos --horizon 12 --step 3
"""
import argparse
import json
from pathlib import Path

from forecast.models import Chronos, Drift, Naive, SeasonalNaive
from forecast.real_data import load_gcis_mfg_new, load_gcis_mfg_new_pre_gap, load_jobmarket_openings
from forecast.report import run_forecast


def main(argv=None):
    parser = argparse.ArgumentParser(description="真實資料：統計基線回測與區間預測")
    parser.add_argument("--series", choices=["jobmarket", "gcis", "gcis-pre-gap"], required=True)
    parser.add_argument("--horizon", type=int, default=12)
    parser.add_argument("--step", type=int, default=3)
    parser.add_argument("--chronos", action="store_true", help="加入 Chronos-Bolt；需安裝模型依賴")
    parser.add_argument("--chronos-model-id", default="amazon/chronos-bolt-tiny",
                        help="Hugging Face Chronos-Bolt 模型 ID（預設 tiny，CPU 可執行）")
    parser.add_argument("--out", type=Path, default=Path("reports/forecast_real"))
    args = parser.parse_args(argv)
    if args.horizon < 1 or args.step < 1:
        parser.error("horizon and step must be positive")

    loaders = {"jobmarket": load_jobmarket_openings, "gcis": load_gcis_mfg_new,
               "gcis-pre-gap": load_gcis_mfg_new_pre_gap}
    series = loaders[args.series]()
    factories, skipped = [Naive, SeasonalNaive, Drift], {}
    if args.chronos:
        available, reason = Chronos.available()
        if available:
            factories.append(lambda: Chronos(args.chronos_model_id))
        else:
            skipped["chronos"] = reason
    result = run_forecast(series, args.horizon, factories=factories, skipped=skipped,
                          step=args.step, out_dir=args.out)
    if args.series == "gcis-pre-gap":
        result["warnings"].append("本次指定缺口前歷史段，只到 2025-07；要使用已補回的官方完整資料，請用 --series gcis。")
    elif args.series == "gcis":
        result["warnings"].append("2025-08/09 使用官方月報觀測值；跨期行業名稱已做別名對照，長期趨勢仍須留意分類調整。資料截止日以 series.last_period 為準。")
    else:
        result["warnings"].append("資料只涵蓋公立就業服務系統，且截至 2026-06；輸出以該月為起點，不能解讀為當前所有月份的未來預測，更不能解讀為全市所有雇主或特定區域、行業的職缺。")
    path = args.out / f"{series.series_id}_forecast.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"series": result["series"], "selected_model": result["selected_model"],
                      "leaderboard": result["backtest"]["leaderboard"],
                      "skipped_models": result["backtest"]["skipped_models"],
                      "warnings": result["warnings"], "output": str(path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
