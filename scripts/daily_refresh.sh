#!/usr/bin/env sh
# 每天更新經濟部商工資料（Linux／macOS 用 cron 排程）
#
#   crontab -e 加一行（每天 06:00）：
#   0 6 * * * /path/to/gcis-talent-radar/scripts/daily_refresh.sh
#
# 用專案的 .venv（有的話），紀錄附加在 data/logs/daily_refresh.log；與伺服器內建排程共用鎖檔，不會重複跑。
cd "$(dirname "$0")/.." || exit 1
PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python
mkdir -p data/logs
PYTHONUTF8=1 "$PY" -m etl.daily_refresh "$@" >> data/logs/daily_refresh.log 2>&1
