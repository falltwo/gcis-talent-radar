"""Sliding-window caps for the unauthenticated, paid model endpoints on the home page.

Same idea as api/recruitment_agent.reserve_model_call (a global one-minute window), plus a
per-client cap because these endpoints have no session. Over a cap, the caller returns 429
and the page falls back to its rule-based text.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_all: deque[float] = deque()
_by_client: dict[str, deque[float]] = defaultdict(deque)
WINDOW = 60.0


def _limit(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def reserve(client: str) -> bool:
    """Record one call for `client`; False when the global or per-client cap is reached."""
    now = time.monotonic()
    with _lock:
        for calls in (_all, _by_client[client]):
            while calls and calls[0] < now - WINDOW:
                calls.popleft()
        if len(_all) >= _limit("SITE_MODEL_CALLS_PER_MINUTE", 30) \
                or len(_by_client[client]) >= _limit("SITE_MODEL_CALLS_PER_CLIENT_PER_MINUTE", 10):
            return False
        _all.append(now)
        _by_client[client].append(now)
        return True


def reset() -> None:
    with _lock:
        _all.clear()
        _by_client.clear()
