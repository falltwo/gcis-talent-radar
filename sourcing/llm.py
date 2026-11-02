"""OpenRouter 上的 gpt-6-luna：只負責把需求轉成搜尋條件、把公開頁面文字整理成摘要。

沒有金鑰或呼叫失敗時回傳 None，呼叫端改用規則版結果，不讓整個流程中斷。
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import requests

DEFAULT_MODEL = "openai/gpt-6-luna"


def has_key() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())


def chat_json(system: str, user: str, schema_name: str, schema: dict[str, Any], *,
              max_tokens: int = 800) -> Optional[dict[str, Any]]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return None
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    payload = {
        "model": os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL).strip(),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
        "reasoning_effort": "none",
        "max_completion_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", "http://localhost:8888"),
        "X-Title": os.environ.get("OPENROUTER_APP_NAME", "Taichung Talent Radar"),
    }
    try:
        response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=(10, 60))
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
        return None
