"""Compatibility CLI: use the same audited producer as the daily refresh.

Run `python -m etl.build_district_stats` for the canonical entry point.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from etl.build_district_stats import OUT, build
from etl.build_site_data import write_artifact


def main():
    write_artifact(OUT, build())


if __name__ == '__main__':
    main()
