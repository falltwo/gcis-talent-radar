"""
真實資料 ETL 一鍵執行
    python -m etl.run_real_etl                    # 下載（已下載的跳過）＋整理＋品質檢查
    python -m etl.run_real_etl --skip-fetch       # 只用現有原始檔重新整理
    python -m etl.run_real_etl --api-limit 2000   # GCIS API 補查最多查幾家（預設不查，另外跑）
    python -m etl.run_real_etl --only taiwanjobs  # 只跑某個來源（每日職缺快照用這個）

產出：data/processed/*.csv、data/processed/_catalog.json、reports/DATA_QUALITY.md
"""
import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.sources import (gcis_county_industry, gcis_registry, labor_insurance, moe_education, moea_ee520,
                         taichung_labor_reports, taichung_opendata, taiwanjobs)
from etl.quality import write_quality_report


def _registry(fetch: bool, api_limit: int):
    if fetch:
        gcis_registry.fetch_lists()
        gcis_registry.fetch_tax_registry()
        if api_limit:
            df = gcis_registry.load_lists()
            gcis_registry.fetch_api(gcis_registry.ids_needing_api(df), limit=api_limit)
            items = [i for r in gcis_registry._load_cache().values() for i in r.get("items", [])[:1]]
            gcis_registry.fetch_item_dgbas(items)
    gcis_registry.transform()


STEPS = {
    "gcis_county_industry": lambda f, a: (f and gcis_county_industry.fetch_all(), gcis_county_industry.transform()),
    "taichung_labor_reports": lambda f, a: (f and taichung_labor_reports.fetch_all(), taichung_labor_reports.transform()),
    "moea_ee520": lambda f, a: (f and moea_ee520.fetch_all(), moea_ee520.transform()),
    "labor_insurance": lambda f, a: (f and labor_insurance.fetch_all(), labor_insurance.transform()),
    "taichung_opendata": lambda f, a: (f and taichung_opendata.fetch_all(), taichung_opendata.transform()),
    "moe_education": lambda f, a: (f and moe_education.fetch_all(), moe_education.transform()),
    "taiwanjobs": lambda f, a: (f and taiwanjobs.fetch_snapshot(), taiwanjobs.transform()),
    "gcis_registry": lambda f, a: _registry(f, a),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--api-limit", type=int, default=0)
    ap.add_argument("--only", choices=list(STEPS), action="append")
    args = ap.parse_args()

    failed = []
    for name in args.only or STEPS:
        print(f"\n=== {name} ===")
        t = time.time()
        try:
            STEPS[name](not args.skip_fetch, args.api_limit)
            print(f"  完成（{time.time() - t:.0f} 秒）")
        except Exception:
            traceback.print_exc()
            failed.append(name)
    path = write_quality_report()
    print(f"\n品質報告：{path}")
    if failed:
        print("失敗的步驟：", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
