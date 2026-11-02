"""computer use 瀏覽器：用 typesafe-computer-use 的瀏覽器模式開 Chrome，由 Jev 決定每一步。

- 讀頁面：透過 Chrome DevTools 讀網頁元素與可見文字，不靠截圖辨識。
- Jev 決定：關掉 cookie 橫幅、彈窗等，讓搜尋結果露出來；只允許點擊、捲動、Esc，不打字也不送出表單。
- 點進個人頁：對頁面上的連結送出真的滑鼠點擊；連結不在畫面上才直接開網址。
- 每一步後截圖，給前端即時顯示。

typesafe-computer-use 是選用套件（requirements-sourcing.txt），只在真的要開瀏覽器時才 import。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import urlsplit

from sourcing.extract import Link, clean_text
from sourcing.sites import blocked_reason

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
CHALLENGE_MARKERS = (
    "just a moment", "attention required", "verify you are human", "are you a robot", "captcha",
    "正在執行安全驗證", "請稍候", "驗證您是人類", "http error 4", "http error 5",
)
LINKS_JS = ("JSON.stringify([...document.querySelectorAll('a[href]')].map(a=>"
            "[a.href,(a.innerText||a.getAttribute('aria-label')||'').trim().slice(0,80),a.rel||'']))")
JEV_ACTIONS = {"click", "press_escape", "scroll_down", "scroll_up", "wait", "done", "none"}


class BrowserUnavailable(RuntimeError):
    """瀏覽器或 typesafe-computer-use 無法使用；訊息可直接顯示給使用者。"""


def find_chrome() -> str:
    configured = os.environ.get("CHROME_PATH", "").strip()
    if configured and Path(configured).exists():
        return configured
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    found = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if found:
        return found
    raise BrowserUnavailable("找不到 Chrome；請安裝 Chrome，或用環境變數 CHROME_PATH 指定路徑。")


def _host_allowed(url: str, domains: tuple[str, ...]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


class SourcingBrowser:
    def __init__(self, *, headed: Optional[bool] = None, jev_model: Optional[str] = None):
        self.headed = headed if headed is not None else os.environ.get("SOURCING_HEADED", "") == "1"
        self.jev_model = jev_model or os.environ.get("SOURCING_JEV_MODEL", "typesafe/jev-1.13")
        self._chrome = None
        self._session = None
        self._client = None

    # ------------------------------------------------------------ lifecycle
    def __enter__(self) -> "SourcingBrowser":
        try:
            from typesafe_computer_use.browser import act, cdp
            from typesafe_computer_use.browser.decide import decide
            from typesafe_computer_use.browser.perceive import perceive
        except ImportError as exc:
            raise BrowserUnavailable("尚未安裝 typesafe-computer-use；請執行 pip install -r requirements-sourcing.txt。") from exc
        self._act, self._decide, self._perceive = act, decide, perceive
        cdp.find_chrome = find_chrome  # 原專案只找 macOS 路徑
        try:
            self._chrome = cdp.Chrome(headed=self.headed).start()
            self._session = self._chrome.attach()
        except Exception as exc:  # Chrome 起不來時給可讀的訊息
            self.close()
            raise BrowserUnavailable(f"Chrome 無法啟動：{type(exc).__name__}。") from exc
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if key:
            from typesafe_sdk import TypeSafeClient
            # Jev 走 OpenRouter，沿用同一把 OPENROUTER_API_KEY
            self._client = TypeSafeClient(api_key=key, base_url=os.environ.get(
                "SOURCING_TYPESAFE_BASE_URL", "https://openrouter.ai/api"), timeout=20.0)
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        for obj in (self._client, self._session, self._chrome):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        self._client = self._session = self._chrome = None

    @property
    def jev_ready(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------ reading
    def url(self) -> str:
        return str(self._session.evaluate("location.href") or "")

    def title(self) -> str:
        return clean_text(str(self._session.evaluate("document.title") or ""))

    def links(self) -> list[Link]:
        raw = json.loads(self._session.evaluate(LINKS_JS) or "[]")
        return [Link(href, clean_text(text), rel) for href, text, rel in raw if href.startswith("http")]

    def text(self, limit: int = 80) -> list[str]:
        page = self._perceive(self._session)
        return [clean_text(t.text) for t in page.text[:limit]]

    def screenshot(self) -> str:
        data = self._session.call("Page.captureScreenshot", {"format": "jpeg", "quality": 55})["data"]
        return "data:image/jpeg;base64," + data

    def challenge(self) -> Optional[str]:
        """網站顯示機器人驗證或錯誤頁時回傳原因；系統不嘗試通過驗證。"""
        url = self.url()
        if url.startswith("chrome-error://"):
            return "網站拒絕自動瀏覽（瀏覽器錯誤頁）"
        sample = (self.title() + " " + " ".join(self.text(limit=12))).lower()
        if any(marker in sample for marker in CHALLENGE_MARKERS):
            return "網站顯示機器人驗證或錯誤頁，已跳過，不嘗試繞過"
        return None

    # ------------------------------------------------------------ acting
    def open(self, url: str) -> str:
        reason = blocked_reason(url)
        if reason:
            raise PermissionError(reason)
        detail = self._act.navigate(self._session, url)
        self._act.wait_for_load(self._session)
        time.sleep(float(os.environ.get("SOURCING_PAGE_DELAY", "1.5")))  # 給 JS 頁面渲染，也放慢節奏
        return detail

    def back(self) -> None:
        self._act.go_back(self._session)
        self._act.wait_for_load(self._session)
        time.sleep(0.5)

    def click_link(self, href: str) -> str:
        """點畫面上指向 href 的連結；找不到可點的元素才直接開網址。回傳 click 或 navigate。"""
        page = self._perceive(self._session)
        target = href.rstrip("/")
        for element in page.items:
            if element.href and element.href.split("?")[0].rstrip("/") == target and element.in_view and not element.covered:
                self._act.click(self._session, int(element.index), element, page)
                self._act.wait_for_load(self._session)
                time.sleep(float(os.environ.get("SOURCING_PAGE_DELAY", "1.5")))
                if self.url().split("?")[0].rstrip("/") == target:
                    return "click"
                break
        self.open(href)
        return "navigate"

    def jev_steps(self, goal: str, domains: tuple[str, ...], *, max_steps: int = 3,
                  min_confidence: float = 0.4) -> Iterator[dict[str, Any]]:
        """Jev 一步一步決定動作。只允許點擊、捲動、Esc；離開允許的網域就退回並停止。"""
        if self._client is None:
            return
        history: list[str] = []
        for n in range(1, max_steps + 1):
            page = self._perceive(self._session)
            try:
                decision = self._decide(self._client, goal, page, history, allow_type=False, can_write=False,
                                        model=self.jev_model)
            except Exception as exc:
                yield {"action": "error", "detail": f"Jev 呼叫失敗：{type(exc).__name__}", "confidence": 0.0}
                return
            kind = decision.kind.choice
            confidence = round(float(decision.confidence), 3)
            if kind not in JEV_ACTIONS:
                kind, detail = "none", f"Jev 選了不允許的動作 {decision.kind.choice}，已停止"
            elif kind == "click":
                element = next((e for e in page.items if e.index == decision.chosen_element), None)
                if element is None or (element.href and not _host_allowed(element.href, domains)):
                    kind, detail = "none", "要點的元素不存在或會離開網站，已停止"
                else:
                    detail = self._act.click(self._session, int(element.index), element, page)
                    self._act.wait_for_load(self._session)
            elif kind == "press_escape":
                detail = self._act.press(self._session, "escape")
            elif kind in ("scroll_down", "scroll_up"):
                detail = self._act.scroll(self._session, 3 if kind == "scroll_down" else -3, page)
            else:
                detail = kind
            if not _host_allowed(self.url(), domains):
                self.back()
                yield {"action": kind, "detail": "離開允許的網站，已退回", "confidence": confidence}
                return
            history.append(f"{kind}: {detail}")
            yield {"action": kind, "detail": clean_text(str(detail))[:200], "confidence": confidence}
            if kind in ("done", "none", "wait") or decision.satisfied.noul >= 0.5 or confidence < min_confidence:
                return
