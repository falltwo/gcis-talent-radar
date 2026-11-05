"""伺服器內建的每日更新排程（etl/daily_refresh.py）。

設環境變數 GCIS_DAILY_REFRESH=1 才會啟動；每天 GCIS_DAILY_REFRESH_HOUR 點（預設 6 點，伺服器時區）跑一次。
伺服器啟動時，如果上次成功更新已超過 24 小時，一分鐘後先補跑一次。
多個伺服器程序同時啟動時用鎖檔避免重複執行。

雲端平台的免費服務閒置會休眠，休眠時排程不會跑；這種情況改用平台的排程工作（cron job）每天執行
`python -m etl.daily_refresh`。
"""
import datetime as dt
import os
import threading
import time
from typing import Optional

from config import BASE_DIR

LOCK = BASE_DIR / "data" / "processed" / ".daily_refresh.lock"
STALE_LOCK_HOURS = 6
_thread: Optional[threading.Thread] = None


def enabled() -> bool:
    return os.environ.get("GCIS_DAILY_REFRESH", "").strip().lower() in ("1", "true", "yes")


def acquire_lock() -> bool:
    """建立鎖檔；已有人在跑就回 False（超過 6 小時的鎖當成上次異常結束，清掉重來）。"""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime > STALE_LOCK_HOURS * 3600:
        LOCK.unlink(missing_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def release_lock() -> None:
    LOCK.unlink(missing_ok=True)


def due(now: dt.datetime, last_finished: Optional[str], hour: int) -> bool:
    """該不該跑：從沒跑過、上次跑完已超過 24 小時，或今天的排程時間到了而今天還沒跑。"""
    if not last_finished:
        return True
    last = dt.datetime.fromisoformat(last_finished).replace(tzinfo=None)
    now = now.replace(tzinfo=None)
    if now - last > dt.timedelta(hours=24):
        return True
    return now.hour >= hour and last.date() < now.date()


def run_once() -> Optional[dict]:
    from etl import daily_refresh

    if not acquire_lock():
        return None
    try:
        return daily_refresh.run()
    finally:
        release_lock()


def _loop(hour: int, first_delay: float, check_every: float) -> None:
    from etl import daily_refresh

    time.sleep(first_delay)
    while True:
        last = daily_refresh.last_report().get("finished_at")  # 有步驟失敗也等到下一次排程，不一直重打 API
        if due(dt.datetime.now(), last, hour):
            try:
                result = run_once()
                if result and not result.get("ok"):
                    print("[daily_refresh] 有步驟失敗，詳見 data/processed/_daily_refresh.json")
            except Exception as exc:  # 排程不能讓伺服器掛掉
                print(f"[daily_refresh] 失敗：{exc!r}")
        time.sleep(check_every)


def start(*, hour: Optional[int] = None, first_delay: float = 60, check_every: float = 900) -> Optional[threading.Thread]:
    """啟動背景排程（只在 GCIS_DAILY_REFRESH=1 時）。"""
    global _thread
    if not enabled() or (_thread and _thread.is_alive()):
        return _thread
    hour = int(os.environ.get("GCIS_DAILY_REFRESH_HOUR", "6")) if hour is None else hour
    _thread = threading.Thread(target=_loop, args=(hour, first_delay, check_every), daemon=True,
                               name="gcis-daily-refresh")
    _thread.start()
    return _thread
