"""computer use 瀏覽器：用 typesafe-computer-use 的瀏覽器模式開 Chrome，由 Jev 操作每一步。

- 讀頁面：透過 Chrome DevTools 讀網頁元素與可見文字，不靠截圖辨識。
- Jev 執行：照目標一步步操作（點擊、在搜尋框打字、按 Enter、捲動、返回、Esc）。
  要打的字由呼叫端給（gpt-6-luna 決定），Jev 只決定點哪裡、打在哪個框。
- 即時畫面：另開一條 DevTools 連線接 Chrome 的畫面串流（Page.startScreencast），前端看到的是真的操作過程。
- 安全：只能在搜尋框打字、不碰密碼欄、不送出其他表單；要點的連結會離開網站就拒絕，真的離開就退回。

typesafe-computer-use 是選用套件（requirements-sourcing.txt），只在真的要開瀏覽器時才 import。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
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
# 每個連結再附上外層區塊的文字（例如搜尋結果卡片上的自我介紹），給 gpt-6-luna 挑人用
CARDS_JS = """JSON.stringify([...document.querySelectorAll('a[href]')].map(a => {
  let el = a, ctx = '';
  for (let i = 0; i < 6 && el; i++) {
    el = el.parentElement;
    if (!el) break;
    const t = (el.innerText || '').trim();
    if (t.length >= 60) { ctx = t; break; }
  }
  return [a.href, (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 80), ctx.slice(0, 400)];
}))"""
# 給前端畫點擊標記與方框：座標換算成即時畫面（最大 1280×800）上的像素
FRAME_MAX = (1280, 800)
# 搜尋結果上某個人的整張卡片（連結往外找到有足夠文字的區塊）
CARD_BOX_JS = """((href) => {
  const norm = (u) => u.split('#')[0].split('?')[0].replace(/\\/$/, '');
  const a = [...document.querySelectorAll('a[href]')].find((x) => norm(x.href) === href);
  if (!a) return null;
  let el = a;
  for (let i = 0; i < 6 && el.parentElement; i++) {
    el = el.parentElement;
    if ((el.innerText || '').trim().length >= 60) break;
  }
  const r = el.getBoundingClientRect();
  return {x: r.left, y: r.top, w: r.width, h: r.height, vw: innerWidth, vh: innerHeight};
})(%s)"""
# 個人頁上候選人名字所在的區塊（標題或內容剛好是名字／帳號的元素）
NAME_BOX_JS = """((names) => {
  const want = names.map((n) => n.toLowerCase());
  const els = [...document.querySelectorAll('h1, h2, [itemprop=name], [class*=name], [class*=Name]')];
  const hit = els.find((e) => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.bottom > 0 && r.top < innerHeight && want.includes((e.innerText || '').trim().toLowerCase());
  });
  if (!hit) return null;
  const r = hit.getBoundingClientRect();
  return {x: r.left, y: r.top, w: r.width, h: r.height, vw: innerWidth, vh: innerHeight};
})(%s)"""
SEARCH_FIELD = re.compile(r"search|filter|find|query|whattosearch|what type|搜尋|搜索|查詢|篩選", re.I)
JEV_ACTIONS = {"click", "type_text", "press_enter", "navigate", "press_escape", "scroll_down", "scroll_up",
               "back", "wait", "done", "none"}


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


def frame_box(left: float, top: float, width: float, height: float, vw: float, vh: float) -> dict[str, Any]:
    """網頁座標（CSS px）換算成即時畫面上的方框。"""
    scale = min(FRAME_MAX[0] / vw, FRAME_MAX[1] / vh) if vw and vh else 1.0
    return {"frame": {"w": round(vw * scale), "h": round(vh * scale)},
            "box": {"x": round(left * scale), "y": round(top * scale), "w": round(width * scale), "h": round(height * scale)}}


def element_geometry(element: Any, page: Any) -> Optional[dict[str, Any]]:
    """被點的元素：點擊位置（元素中心）與元素方框，都換算成即時畫面座標；缺座標時回 None。"""
    if not all(isinstance(getattr(o, k, None), (int, float)) for o, k in
               ((element, "x"), (element, "y"), (element, "w"), (element, "h"), (page, "vw"), (page, "vh"))):
        return None
    width = min(element.w, 1400)
    geo = frame_box(element.x - width / 2, element.y - element.h / 2, element.w, element.h, page.vw, page.vh)
    scale = geo["frame"]["w"] / page.vw if page.vw else 1.0
    geo["click"] = {"x": round(element.x * scale), "y": round(element.y * scale)}
    return geo


_JOB = None
_CLEANED = False
_CLEAN_LOCK = threading.Lock()


def bind_to_server(pid: int) -> None:
    """Windows：把 Chrome 放進「伺服器結束就一起結束」的 Job；伺服器被強制關閉或當掉也不會留下 Chrome。"""
    global _JOB
    if os.name != "nt":
        return
    try:
        import win32api
        import win32con
        import win32job

        if _JOB is None:
            job = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
            info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
            _JOB = job
        handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid)
        win32job.AssignProcessToJobObject(_JOB, handle)
    except Exception:
        pass  # 綁不上時還有啟動時的 cleanup_stale_chrome


def cleanup_stale_chrome() -> int:
    """伺服器啟動時清掉上次殘留的 agent Chrome（只認 typesafe 的暫存設定檔 tscu-chrome-*，不碰使用者的 Chrome）。"""
    try:
        import psutil
    except ImportError:
        return 0
    me = os.getpid()
    killed = 0
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if not any(b in name for b in ("chrome", "chromium", "msedge")):
                continue  # 只碰瀏覽器本身，指令列剛好含這些字的其他程式不算
            if "tscu-chrome-" not in cmdline or "--remote-debugging-port" not in cmdline:
                continue
            if any(parent.pid == me for parent in proc.parents()):
                continue  # 這個伺服器自己開的
            proc.kill()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if killed:
        time.sleep(1.0)
    for profile in Path(tempfile.gettempdir()).glob("tscu-chrome-*"):
        shutil.rmtree(profile, ignore_errors=True)  # 還在用的檔案刪不掉，會被略過
    return killed


def _host_allowed(url: str, domains: tuple[str, ...]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


class Screencast:
    """另一條 DevTools 連線，持續收 Chrome 的畫面；只保留最新一張。"""

    def __init__(self, ws_url: str, origin: str, *, max_width: int = 1280, quality: int = 55):
        import websocket  # typesafe-computer-use 的相依套件

        self._ws = websocket.create_connection(ws_url, origin=origin, timeout=30, max_size=64 * 1024 * 1024)
        self._lock = threading.Lock()
        self._frame: Optional[str] = None
        self._seq = 0
        self._stop = threading.Event()
        self._ws.send(json.dumps({"id": 1, "method": "Page.startScreencast", "params": {
            "format": "jpeg", "quality": quality, "maxWidth": max_width, "maxHeight": int(max_width * 0.625)}}))
        self._thread = threading.Thread(target=self._pump, name="sourcing-screencast", daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        while not self._stop.is_set():
            try:
                message = json.loads(self._ws.recv())
            except Exception:
                return
            if message.get("method") != "Page.screencastFrame":
                continue
            params = message["params"]
            with self._lock:
                self._frame, self._seq = params["data"], self._seq + 1
            try:
                self._ws.send(json.dumps({"id": 2, "method": "Page.screencastFrameAck",
                                          "params": {"sessionId": params["sessionId"]}}))
            except Exception:
                return

    def latest(self) -> tuple[int, Optional[str]]:
        with self._lock:
            return self._seq, self._frame

    def close(self) -> None:
        self._stop.set()
        try:
            self._ws.close()
        except Exception:
            pass


class SourcingBrowser:
    def __init__(self, *, headed: Optional[bool] = None, jev_model: Optional[str] = None, screencast: bool = False):
        self.headed = headed if headed is not None else os.environ.get("SOURCING_HEADED", "") == "1"
        self.jev_model = jev_model or os.environ.get("SOURCING_JEV_MODEL", "typesafe/jev-1.13")
        self.want_screencast = screencast
        self.last_outcome = ""
        self.last_click: Optional[dict[str, Any]] = None  # 最近一次 click_link 的座標，給前端畫點擊標記
        self._chrome = None
        self._session = None
        self._client = None
        self._screencast: Optional[Screencast] = None

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
        global _CLEANED
        with _CLEAN_LOCK:  # 這個伺服器第一次開 Chrome 前，先清掉上次被強制結束時留下的
            if not _CLEANED:
                cleanup_stale_chrome()
                _CLEANED = True
        try:
            self._chrome = cdp.Chrome(headed=self.headed).start()
            if self._chrome.proc is not None:
                bind_to_server(self._chrome.proc.pid)
            self._session = self._chrome.attach()
            if self.want_screencast:
                self._screencast = Screencast(self._chrome.page_target(), self._chrome.origin)
        except Exception as exc:  # Chrome 起不來時給可讀的訊息
            self.close()
            raise BrowserUnavailable(f"Chrome 無法啟動：{type(exc).__name__}。") from exc
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if key:
            from typesafe_sdk import TypeSafeClient
            # Jev 走 OpenRouter，沿用同一把 OPENROUTER_API_KEY
            from sourcing.usage import MeteredJev

            self._client = MeteredJev(TypeSafeClient(api_key=key, base_url=os.environ.get(
                "SOURCING_TYPESAFE_BASE_URL", "https://openrouter.ai/api"), timeout=20.0))
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        for obj in (self._screencast, self._client, self._session, self._chrome):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        self._screencast = self._client = self._session = self._chrome = None

    @property
    def jev_ready(self) -> bool:
        return self._client is not None

    def latest_frame(self) -> tuple[int, Optional[str]]:
        """即時畫面的最新一張（序號、base64 JPEG）；沒開串流時回 (0, None)。"""
        return self._screencast.latest() if self._screencast else (0, None)

    # ------------------------------------------------------------ reading
    def url(self) -> str:
        return str(self._session.evaluate("location.href") or "")

    def title(self) -> str:
        return clean_text(str(self._session.evaluate("document.title") or ""))

    def links(self) -> list[Link]:
        raw = json.loads(self._session.evaluate(LINKS_JS) or "[]")
        return [Link(href, clean_text(text), rel) for href, text, rel in raw if href.startswith("http")]

    def result_cards(self) -> list[tuple[str, str, str]]:
        """每個連結的 (網址, 文字, 外層區塊文字)。"""
        raw = json.loads(self._session.evaluate(CARDS_JS) or "[]")
        return [(href, clean_text(text), clean_text(ctx)) for href, text, ctx in raw if href.startswith("http")]

    def _box(self, js: str, arg: Any) -> Optional[dict[str, Any]]:
        try:
            r = self._session.evaluate(js % json.dumps(arg))
        except Exception:
            return None
        if not r or not r.get("w") or not r.get("h"):
            return None
        return frame_box(r["x"], r["y"], r["w"], r["h"], r["vw"], r["vh"])

    def card_box(self, href: str) -> Optional[dict[str, Any]]:
        """搜尋結果上這位候選人的卡片在即時畫面中的位置。"""
        return self._box(CARD_BOX_JS, href.rstrip("/"))

    def name_box(self, *names: str) -> Optional[dict[str, Any]]:
        """個人頁上候選人名字所在的區塊。"""
        return self._box(NAME_BOX_JS, [n for n in names if n])

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
    def _settle(self, *, max_wait: float = 6.0) -> None:
        """等頁面可以操作：DOM 載入後就繼續，不等廣告、追蹤碼等第三方內容（有些網站永遠載不完）。"""
        start = time.monotonic()
        while time.monotonic() - start < max_wait:
            state = self._session.evaluate("document.readyState")
            if state == "complete" or (state == "interactive" and time.monotonic() - start > 1.0):
                break
            time.sleep(0.1)
        time.sleep(float(os.environ.get("SOURCING_PAGE_DELAY", "1.5")))  # 給 JS 頁面渲染，也放慢節奏

    def open(self, url: str) -> str:
        reason = blocked_reason(url)
        if reason:
            raise PermissionError(reason)
        detail = self._act.navigate(self._session, url)
        self._settle()
        return detail

    def back(self) -> None:
        self._act.go_back(self._session)
        self._settle(max_wait=4.0)

    def visible_link(self, href: str) -> bool:
        """畫面上看得到、沒被擋住的連結有沒有指向 href；沒有就不必請 Jev 找（例如搜尋結果只列作品不列作者）。"""
        target = href.rstrip("/")
        page = self._perceive(self._session)
        return any(e.href and e.href.split("?")[0].rstrip("/") == target and e.in_view and not e.covered
                   for e in page.items)

    def click_link(self, href: str) -> str:
        """點畫面上指向 href 的連結；找不到可點的元素才直接開網址。回傳 click 或 navigate。"""
        page = self._perceive(self._session)
        target = href.rstrip("/")
        self.last_click = None
        for element in page.items:
            if element.href and element.href.split("?")[0].rstrip("/") == target and element.in_view and not element.covered:
                self.last_click = element_geometry(element, page)
                self._act.click(self._session, int(element.index), element, page)
                self._settle()
                if self.url().split("?")[0].rstrip("/") == target:
                    return "click"
                break
        self.open(href)
        return "navigate"

    def jev_goal(self, goal: str, domains: tuple[str, ...], *, text: Optional[str] = None,
                 entry_url: Optional[str] = None, max_steps: int = 6,
                 min_confidence: float = 0.35) -> Iterator[dict[str, Any]]:
        """Jev 照目標一步步操作瀏覽器。

        `text` 是要打進搜尋框的字（由 gpt-6-luna 決定）；Jev 只決定打在哪個框、點哪裡、何時按 Enter。
        `entry_url` 是 Jev 選「開網址」時唯一能去的頁面。結束原因寫在 `self.last_outcome`。
        """
        self.last_outcome = "skipped"
        if self._client is None:
            return
        history: list[str] = []
        typed = False
        noops = 0
        for _ in range(max_steps):
            page = self._perceive(self._session)
            try:
                decision = self._decide(self._client, goal, page, history, allow_type=bool(text),
                                        can_write=bool(text), model=self.jev_model)
            except Exception as exc:
                self.last_outcome = "error"
                yield {"action": "error", "detail": f"Jev 呼叫失敗：{type(exc).__name__}", "confidence": 0.0}
                return
            kind = decision.kind.choice
            confidence = round(float(decision.confidence), 3)
            element = next((e for e in page.items if e.index == decision.chosen_element), None)
            refused = ""
            detail = kind
            geometry = None
            if kind not in JEV_ACTIONS:
                refused = f"不允許的動作 {kind}"
            elif kind == "click":
                if element is None:
                    refused = "要點的元素不存在"
                elif element.href and not _host_allowed(element.href, domains):
                    refused = "這個連結會離開網站"
                else:
                    geometry = element_geometry(element, page)
                    self._act.click(self._session, int(element.index), element, page)
                    detail = f"點擊「{(element.name or element.tag)[:40]}」"
                    self._settle()
            elif kind == "type_text":
                if not text or element is None or not element.field or element.secret:
                    refused = "只能在搜尋框打字"
                elif not SEARCH_FIELD.search(element.name or ""):
                    refused = f"「{element.name[:30]}」不是搜尋框"
                else:
                    geometry = element_geometry(element, page)
                    self._act.type_text(self._session, int(element.index), text)
                    typed = True
                    detail = f"在「{element.name[:30]}」輸入：{text}"
            elif kind == "press_enter":
                if not typed:
                    refused = "只有輸入搜尋字之後才能按 Enter"
                else:
                    self._act.press(self._session, "enter")
                    detail = "按 Enter 送出搜尋"
                    self._settle()
            elif kind == "navigate":
                if not entry_url:
                    refused = "不允許自己開網址"
                else:
                    self.open(entry_url)
                    detail = "回到網站入口頁"
            elif kind == "press_escape":
                self._act.press(self._session, "escape")
                detail = "按 Esc 關閉彈窗"
            elif kind in ("scroll_down", "scroll_up"):
                self._act.scroll(self._session, 3 if kind == "scroll_down" else -3, page)
                detail = "往下捲動" if kind == "scroll_down" else "往上捲動"
            elif kind == "back":
                self.back()
                detail = "返回上一頁"
            elif kind == "done":
                detail = "Jev 判斷目標已完成"
            elif kind == "none":
                detail = "Jev 判斷這一頁無法繼續"
            elif kind == "wait":
                detail = "等待頁面"
            if refused:
                noops += 1
                kind, detail = "refused", f"拒絕 Jev 的動作：{refused}"
            if not _host_allowed(self.url(), domains):
                self.back()
                self.last_outcome = "left_site"
                yield {"action": kind, "detail": "離開允許的網站，已退回", "confidence": confidence}
                return
            history.append(f"{kind}: {detail}")
            step: dict[str, Any] = {"action": kind, "detail": clean_text(str(detail))[:200], "confidence": confidence}
            if geometry:
                step["geometry"] = geometry
            yield step
            if kind == "done" or decision.satisfied.noul >= 0.5:
                self.last_outcome = "done"
                return
            if kind == "none":
                self.last_outcome = "blocked"
                return
            if confidence < min_confidence:
                self.last_outcome = "low_confidence"
                return
            if noops >= 2:
                self.last_outcome = "stuck"
                return
        self.last_outcome = "max_steps"
