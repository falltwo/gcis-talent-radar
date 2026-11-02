"""網站官方 API：個人頁會跳機器人驗證時改用官方 API 讀公開資料（不繞過驗證）。"""
from __future__ import annotations

from typing import Any, Optional

import requests

STACKEXCHANGE = "https://api.stackexchange.com/2.3"


def stackoverflow_user(user_id: str, *, timeout: float = 15.0) -> Optional[dict[str, Any]]:
    """Stack Exchange 官方 API：公開的顯示名稱、聲望、地點、網站與最常回答的標籤。"""
    params = {"site": "stackoverflow"}
    try:
        user = requests.get(f"{STACKEXCHANGE}/users/{user_id}", params=params, timeout=timeout)
        user.raise_for_status()
        items = user.json().get("items") or []
        if not items:
            return None
        tags = requests.get(f"{STACKEXCHANGE}/users/{user_id}/top-tags", params={**params, "pagesize": 6},
                            timeout=timeout)
        tags.raise_for_status()
    except (requests.RequestException, ValueError):
        return None
    info = items[0]
    return {
        "display_name": info.get("display_name") or "",
        "reputation": info.get("reputation"),
        "location": info.get("location") or "",
        "website_url": info.get("website_url") or "",
        "link": info.get("link") or "",
        "top_tags": [t.get("tag_name") for t in tags.json().get("items", []) if t.get("tag_name")],
    }
