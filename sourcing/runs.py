"""以「搜尋任務」為單位給前端接：建立後在背景執行，前端可以訂閱事件、查狀態、取消。

- 事件全部留在記憶體，訂閱時從頭（或從 Last-Event-ID 之後）重送，所以斷線重連不會漏。
- 即時畫面（frame）只送最新一張，不留存。
- 只存在這個行程的記憶體裡：多個 worker 或重啟後就查不到，正式部署要換成共用儲存。
- 每個任務會開一個 Chrome，同時執行的任務數有上限（SOURCING_MAX_RUNS，預設 2）。
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from sourcing import service
from sourcing.browser import SourcingBrowser

FINAL_STATUS = {"done": "done", "error": "error", "rejected": "rejected", "no_public_work": "no_public_work"}


class RunnerBusy(RuntimeError):
    """同時執行的任務已達上限。"""


@dataclass
class Run:
    id: str
    prep: service.Prepared
    created_at: float = field(default_factory=time.time)
    status: str = "running"  # running | done | error | cancelled | rejected | no_public_work
    finished_at: Optional[float] = None
    events: list[dict] = field(default_factory=list)
    stop: threading.Event = field(default_factory=threading.Event)
    browser: Any = None
    cond: threading.Condition = field(default_factory=threading.Condition)

    @property
    def finished(self) -> bool:
        return self.status != "running"

    def append(self, event: dict) -> None:
        with self.cond:
            self.events.append(event)
            if event["type"] in FINAL_STATUS:
                self.status = "cancelled" if self.stop.is_set() and event["type"] == "done" else FINAL_STATUS[event["type"]]
            self.cond.notify_all()

    def finish(self, status: Optional[str] = None) -> None:
        with self.cond:
            if status or self.status == "running":
                self.status = status or ("cancelled" if self.stop.is_set() else "error")
            self.finished_at = self.finished_at or time.time()
            self.browser = None
            self.cond.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self.cond:
            events = list(self.events)
            status, finished_at = self.status, self.finished_at
        plan = next((e["plan"] for e in events if e["type"] in ("plan", "done", "no_public_work") and e.get("plan")), None)
        final = next((e for e in reversed(events) if e["type"] in FINAL_STATUS), None)
        return {
            "run_id": self.id,
            "status": status,
            "query": self.prep.query,
            "created_at": self.created_at,
            "finished_at": finished_at,
            "plan": plan,
            "steps": sum(1 for e in events if e["type"] == "step"),
            "candidates": [e["candidate"] for e in events if e["type"] == "candidate"],
            "skipped": [e for e in events if e["type"] in ("candidate_skipped", "site_skipped", "site_error")],
            "message": (final or {}).get("message") or (final or {}).get("reason") or (final or {}).get("advice"),
            "usage": (final or {}).get("usage"),
            "event_count": len(events),
        }


class RunRegistry:
    def __init__(self, *, max_running: Optional[int] = None, ttl_seconds: float = 1800,
                 browser_factory: Any = None):
        self.max_running = max_running or int(os.environ.get("SOURCING_MAX_RUNS", "2"))
        self.ttl_seconds = ttl_seconds
        self.browser_factory = browser_factory
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def _cleanup(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        for run_id in [r.id for r in self._runs.values() if r.finished_at and r.finished_at < cutoff]:
            del self._runs[run_id]

    def start(self, prep: service.Prepared) -> Run:
        with self._lock:
            self._cleanup()
            if prep.runnable and sum(1 for r in self._runs.values() if not r.finished) >= self.max_running:
                raise RunnerBusy(f"目前已有 {self.max_running} 個搜尋在執行，請稍後再試。")
            run = Run(uuid.uuid4().hex[:12], prep)
            self._runs[run.id] = run
        if not prep.runnable:  # 被護欄擋下或職類沒有公開作品：不開瀏覽器，直接結束
            for event in service.stream(prep):
                run.append(event)
            run.finish()
            return run
        threading.Thread(target=self._work, args=(run,), name=f"sourcing-{run.id}", daemon=True).start()
        return run

    def _work(self, run: Run) -> None:
        factory = self.browser_factory or (lambda: service.SourcingBrowser(screencast=True))

        def make() -> SourcingBrowser:
            run.browser = factory()
            return run.browser

        try:
            for event in service.stream(run.prep, browser_factory=make, stop=run.stop):
                run.append(event)
        except Exception as exc:  # 背景執行緒的例外要寫成事件，前端才看得到
            run.append({"type": "error", "reason": f"找人流程中斷：{type(exc).__name__}"})
        finally:
            run.finish()

    def get(self, run_id: str) -> Optional[Run]:
        with self._lock:
            return self._runs.get(run_id)

    def cancel(self, run_id: str) -> Optional[Run]:
        run = self.get(run_id)
        if run is not None and not run.finished:
            run.stop.set()
        return run


def follow(run: Run, *, after: int = 0, frames: bool = True, fps: float = 6.0) -> Iterator[tuple[Optional[int], dict]]:
    """依序產生 (事件編號, 事件)；即時畫面的編號是 None。任務結束且事件送完就停止。"""
    interval = 1.0 / max(fps, 0.5)
    index = max(after, 0)
    last_seq, last_sent = 0, 0.0
    while True:
        with run.cond:
            if index >= len(run.events) and not run.finished:
                run.cond.wait(timeout=interval)
            pending = run.events[index:]
            finished = run.finished
            browser = run.browser
        for event in pending:
            index += 1
            yield index, event
        if frames and browser is not None:
            latest = getattr(browser, "latest_frame", None)
            if latest is not None:
                seq, data = latest()
                now = time.monotonic()
                if data and seq != last_seq and now - last_sent >= interval:
                    last_seq, last_sent = seq, now
                    yield None, {"type": "frame", "data": "data:image/jpeg;base64," + data}
        if finished and index >= len(run.events):
            return


registry = RunRegistry()
