"""記錄一次找人流程實際用掉的 token 與費用，結束時放進 done 事件。

gpt-6-luna 的花費用 OpenRouter 回報的 cost；沒回報時用 token 數乘單價估算。
Jev（TypeSafe SDK）只回報 token 數，費用一律用單價估算。單價可用環境變數調整（美元／每百萬 token）。
"""
from __future__ import annotations

import os
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Optional


def _price(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Usage:
    luna_calls: int = 0
    luna_input: int = 0
    luna_output: int = 0
    luna_cost_reported: float = 0.0
    luna_cost_estimated: float = 0.0
    jev_calls: int = 0
    jev_input: int = 0
    jev_output: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add_luna(self, prompt: Optional[int], completion: Optional[int], cost: Optional[float]) -> None:
        p, c = int(prompt or 0), int(completion or 0)
        estimate = (p * _price("SOURCING_LUNA_PRICE_IN", 0.10) + c * _price("SOURCING_LUNA_PRICE_OUT", 0.50)) / 1e6
        with self._lock:
            self.luna_calls += 1
            self.luna_input += p
            self.luna_output += c
            self.luna_cost_reported += float(cost) if isinstance(cost, (int, float)) else estimate
            self.luna_cost_estimated += estimate

    def add_jev(self, input_tokens: Optional[int], output_tokens: Optional[int]) -> None:
        with self._lock:
            self.jev_calls += 1
            self.jev_input += int(input_tokens or 0)
            self.jev_output += int(output_tokens or 0)

    def as_dict(self) -> dict[str, Any]:
        jev_cost = (self.jev_input * _price("SOURCING_JEV_PRICE_IN", 0.042)
                    + self.jev_output * _price("SOURCING_JEV_PRICE_OUT", 0.0)) / 1e6
        return {
            "gpt_6_luna": {"calls": self.luna_calls, "input_tokens": self.luna_input,
                           "output_tokens": self.luna_output, "cost_usd": round(self.luna_cost_reported, 6)},
            "jev": {"calls": self.jev_calls, "input_tokens": self.jev_input, "output_tokens": self.jev_output,
                    "cost_usd": round(jev_cost, 6), "cost_is_estimate": True},
            "total_tokens": self.luna_input + self.luna_output + self.jev_input + self.jev_output,
            "total_cost_usd": round(self.luna_cost_reported + jev_cost, 6),
        }


_current: ContextVar[Optional[Usage]] = ContextVar("sourcing_usage", default=None)


def bind(usage: Usage) -> None:
    """讓這個執行緒之後的模型呼叫都記到 usage（prepare 與 stream 各自在自己的執行緒呼叫）。"""
    _current.set(usage)


def current() -> Optional[Usage]:
    return _current.get()


class MeteredJev:
    """包住 TypeSafeClient，每次 system_one 都把 token 數記下來；其他屬性原樣轉給原本的 client。"""

    def __init__(self, client: Any):
        self._client = client

    def system_one(self, *args: Any, **kwargs: Any) -> Any:
        response = self._client.system_one(*args, **kwargs)
        usage = current()
        if usage is not None:
            u = getattr(response, "usage", None)
            usage.add_jev(getattr(u, "input_tokens", None), getattr(u, "output_tokens", None))
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)
