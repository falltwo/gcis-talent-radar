"""找人流程：守門 → 規劃 → 依職類挑網站 → computer use 搜尋與開個人頁 → 整理摘要。

分工：gpt-6-luna 決定搜尋字、挑誰點進去、判斷符不符合；Jev 實際操作瀏覽器（點擊、打字、按 Enter）。
Jev 沒完成時改用確定性的備案（直接開網址、直接點連結），並在事件裡標明。

`prepare()` 先做不需要瀏覽器的檢查並寫稽核紀錄；`stream()` 一步一步產生事件；`stream_live()` 在旁邊
另外送出 Chrome 的即時畫面（frame 事件）。事件型別見 docs/SOURCING.md。
"""
from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generator, Iterator, Optional

from agent.audit_log import write_agent_audit
from agent.prompt_guard import inspect_hiring_prompt
from sourcing import decider, planner
from sourcing import usage as usage_meter
from sourcing.browser import BrowserUnavailable, SourcingBrowser
from sourcing.extract import (Candidate, from_openalex, from_orcid, from_stackoverflow, result_cards,
                              summarize)
from sourcing.sites import Site, blocked_reason, sites_for

MAX_PAGES = 5   # 每個網站最多看幾頁搜尋結果
MAX_CARDS = 40  # 一頁最多讀幾張候選人卡片
API_SITES = {  # 只走官方 API 的網站：說明、取資料的函式、顯示用網址
    "openalex": ("搜尋論文作者", from_openalex, "https://api.openalex.org"),
    "orcid": ("搜尋研究者", from_orcid, "https://pub.orcid.org"),
    "stackexchange": ("查技能標籤的回答排行", from_stackoverflow, "https://api.stackexchange.com"),
}
DONE_MESSAGE = "只列出公開頁面的連結，未蒐集 Email 或電話；聯絡前請自行確認候選人的公開意願。"
POPUP_GOAL = ("Close any cookie banner, sign-in prompt or popup so that the list of search results "
            "(people, users or their work) is visible. Do not open any result and do not sign in.")


@dataclass
class Prepared:
    query: str
    max_candidates: int
    screenshots: bool
    plan: Optional[planner.Plan] = None
    sites: list[Site] = field(default_factory=list)
    skipped: list[Site] = field(default_factory=list)
    final_event: Optional[dict[str, Any]] = None  # 不需要開瀏覽器就結束時的事件
    usage: usage_meter.Usage = field(default_factory=usage_meter.Usage)

    @property
    def runnable(self) -> bool:
        return self.final_event is None


def _scope(decision: str, reason: str) -> dict[str, Any]:
    return {"decision": decision, "category": "SOURCING", "implementation": "SourcingCategoryRules",
            "version": "sourcing-v1", "rule_score": None, "reason": reason}


def prepare(query: str, *, max_candidates: int = 5, site_ids: Optional[list[str]] = None,
            screenshots: bool = True) -> Prepared:
    """守門與規劃。寫不進稽核紀錄時丟 AuditLogError，呼叫端應回 503。"""
    prep = Prepared(query.strip(), max(1, min(int(max_candidates), 20)), screenshots)
    usage_meter.bind(prep.usage)
    # 找人一定是招募情境；補上「招募」讓「找 30 歲以下的…」這種寫法也會被公平招募護欄判斷
    guard = inspect_hiring_prompt("招募：" + prep.query)
    if guard["decision"] == "REJECT":
        write_agent_audit(prep.query, scope_guard=_scope("ALLOW", "找人需求"), prompt_guard=guard,
                          outcome="SOURCING_REJECTED_FAIR_HIRING", model_called=False)
        prep.final_event = {"type": "rejected", "reason": guard["reason"], "matched_traits": guard["matched_traits"]}
        return prep

    prep.plan = planner.plan(prep.query)
    if not prep.plan.has_public_work:
        write_agent_audit(prep.query, scope_guard=_scope("REJECT", "職類無公開作品"), prompt_guard=guard,
                          outcome="SOURCING_NO_PUBLIC_WORK", model_called=prep.plan.source == "llm")
        prep.final_event = {"type": "no_public_work", "plan": prep.plan.as_dict(),
                            "advice": " ".join(prep.plan.notes)}
        return prep

    picked = sites_for(prep.plan.categories, only=site_ids)
    prep.sites = [s for s in picked if s.available]
    prep.skipped = [s for s in picked if not s.available]
    write_agent_audit(prep.query, scope_guard=_scope("ALLOW", "找人需求"), prompt_guard=guard,
                      outcome="SOURCING_STARTED" if prep.sites else "SOURCING_NO_SITE",
                      model_called=prep.plan.source == "llm", tool_calls=[s.id for s in prep.sites])
    if not prep.sites:
        prep.final_event = {"type": "done", "count": 0, "plan": prep.plan.as_dict(),
                            "message": "這個職類目前沒有可用的網站。"}
    return prep


def _same_page(a: str, b: str) -> bool:
    return a.split("#")[0].split("?")[0].rstrip("/").lower() == b.split("#")[0].split("?")[0].rstrip("/").lower()


def stream(prep: Prepared, *, browser_factory: Optional[Callable[[], SourcingBrowser]] = None,
           stop: Optional[threading.Event] = None) -> Iterator[dict]:
    browser_factory = browser_factory or SourcingBrowser
    stopped = lambda: stop is not None and stop.is_set()  # noqa: E731
    usage_meter.bind(prep.usage)
    if not prep.runnable:
        yield {**prep.final_event, "usage": prep.usage.as_dict()}
        return
    plan = prep.plan
    yield {"type": "plan", "plan": plan.as_dict(), "sites": [{"id": s.id, "name": s.name} for s in prep.sites]}
    for s in prep.skipped:
        yield {"type": "site_skipped", "site": s.id, "name": s.name, "reason": s.unavailable_reason}

    candidates: list[Candidate] = []
    step_no = 0

    def step(site: Site, action: str, detail: str, browser: Optional[SourcingBrowser] = None, **extra: Any) -> dict:
        nonlocal step_no
        step_no += 1
        if extra.get("geometry") is None:
            extra.pop("geometry", None)
        event = {"type": "step", "n": step_no, "site": site.id, "action": action, "detail": detail,
                 "url": browser.url() if browser else extra.pop("url", ""), **extra}
        if prep.screenshots and browser is not None:
            try:
                event["screenshot"] = browser.screenshot()
            except Exception:
                event["screenshot"] = None
        return event

    def jev_step(site: Site, jev: dict, browser: SourcingBrowser) -> dict:
        extra = {"confidence": jev["confidence"]}
        if jev.get("geometry"):
            extra["geometry"] = jev["geometry"]
        return step(site, f"jev_{jev['action']}", jev["detail"], browser, **extra)

    def browser_call(browser: SourcingBrowser, name: str, *args: Any) -> Optional[dict]:
        """座標是給前端的加分資訊：假的或舊版瀏覽器沒有這些方法時就略過。"""
        method = getattr(browser, name, None)
        return method(*args) if method else None

    def decision(site: Site, what: str, detail: str, source: str) -> dict:
        return {"type": "decision", "site": site.id, "what": what, "detail": detail,
                "by": "gpt-6-luna" if source == "llm" else "rules"}

    nearby: list[Candidate] = []

    def fill_nearby() -> Iterator[dict]:
        """指定城市的來源都找完還有名額：才補同國家其他城市的人（已標為部分符合）。"""
        for cand in nearby:
            if len(candidates) >= prep.max_candidates or stopped():
                return
            candidates.append(cand)
            yield {"type": "candidate", "candidate": cand.as_dict()}

    # 只走官方 API 的網站（OpenAlex、ORCID、Stack Overflow）先跑，不需要開瀏覽器
    api_sites = [s for s in prep.sites if s.search_url is None]
    browser_sites = [s for s in prep.sites if s.search_url is not None]
    for i, site in enumerate(api_sites):
        remaining = prep.max_candidates - len(candidates)
        if remaining <= 0 or stopped():
            break
        quota = math.ceil(remaining / (len(prep.sites) - i))
        what, fetch, api_url = API_SITES[site.profile_api]
        if site.profile_api == "stackexchange" and plan.terms.location:
            yield {"type": "notice", "message": "Stack Overflow 的排行不分地點，官方 API 也不能依地點搜尋，"
                                                "指定城市時通常找不到人；同國家其他城市的人會列為部分符合。"}
        yield step(site, "read_api", f"用 {site.name} 官方 API {what}：{plan.terms.text()}", url=api_url, screenshot=None)
        try:
            found = fetch(site, plan, limit=quota * 2)  # 多抓一些，判定「不符合」的會略過
        except Exception as exc:  # 一個網站出錯不影響其他網站
            found = None
            yield {"type": "site_error", "site": site.id, "reason": f"{site.name} 發生錯誤（{type(exc).__name__}），已跳過"}
            continue
        if found is None:
            yield {"type": "site_error", "site": site.id, "reason": f"{site.name} API 暫時無法使用"}
            continue
        if not found:
            yield {"type": "site_error", "site": site.id, "reason": f"{site.name} 沒有找到符合條件的人"}
        taken = 0
        for cand in found:
            if taken >= quota:
                break
            if cand.fit == "不符合":
                yield {"type": "candidate_skipped", "site": site.id, "name": cand.name, "reason": cand.fit_reason}
                continue
            if cand.nearby:
                nearby.append(cand)  # 同國家其他城市：等指定城市的來源都找完，還有名額才補
                continue
            candidates.append(cand)
            taken += 1
            yield {"type": "candidate", "candidate": cand.as_dict()}
    if not browser_sites or len(candidates) >= prep.max_candidates or stopped():
        yield from fill_nearby()
        yield {"type": "done", "count": len(candidates), "plan": plan.as_dict(), "message": DONE_MESSAGE,
               "usage": prep.usage.as_dict(), "cancelled": stopped()}
        return

    def search_site(browser: SourcingBrowser, site: Site, quota: int) -> Iterator[dict]:
        """單一網站：搜尋、挑人、逐一讀個人頁。這裡丟出的例外只會結束這個網站。"""
        # 1. 搜尋：gpt-6-luna 決定要打的字（GitHub 先用官方 API 數人數，太少就放寬），
        #    Jev 在入口頁的搜尋框操作；沒完成就直接開同一組搜尋字的結果頁
        text, source, note = decider.search_text(site, plan, need=min(quota, 10))
        yield decision(site, "search_text", f"在 {site.name} 搜尋：{text}" + (f"。{note}" if note else ""), source)
        search_url = site.query_url(text) if site.query_url else site.search_url(plan.terms)
        searched = False
        try:
            if browser.jev_ready and site.entry_url:
                browser.open(site.entry_url)
                yield step(site, "open_entry", f"開啟 {site.name}", browser)
                goal = (f"Search this website for: {text}. Click the main search box, type the text, and press "
                        "Enter, until the search results are shown. Do not sign in.")
                for jev in browser.jev_goal(goal, site.domains, text=text, entry_url=site.entry_url):
                    yield jev_step(site, jev, browser)
                    if stopped():
                        return
                searched = bool(result_cards(site, browser.result_cards()))
                if not searched:
                    yield step(site, "fallback", f"Jev 沒有完成搜尋（{browser.last_outcome}），改直接開搜尋結果頁")
            if not searched:
                browser.open(search_url)
                yield step(site, "open_search", f"在 {site.name} 搜尋：{text}", browser)
        except PermissionError as exc:
            yield {"type": "site_error", "site": site.id, "reason": str(exc)}
            return
        reason = browser.challenge()
        if reason:
            yield {"type": "site_error", "site": site.id, "reason": reason}
            return
        if not searched:
            for jev in browser.jev_goal(POPUP_GOAL, site.domains, max_steps=3):
                yield jev_step(site, jev, browser)

        # 2. 挑人：gpt-6-luna 從搜尋結果卡片挑出最值得看的幾位
        cards = result_cards(site, browser.result_cards(), limit=MAX_CARDS)
        if not cards:
            yield {"type": "site_error", "site": site.id, "reason": "搜尋結果頁沒有找到候選人連結"}
            return
        first_page = results_url = browser.url()
        seen: set[str] = set()
        taken = 0
        page = 1
        while True:
            fresh = [c for c in cards if c.url not in seen][:MAX_CARDS]
            if not fresh:
                # 這一頁看完了還不夠：換下一頁或往下捲，最多 MAX_PAGES 頁
                if taken >= quota or page >= MAX_PAGES or stopped():
                    return
                page += 1
                if site.page_url:
                    browser.open(site.page_url(first_page, page))
                    yield step(site, "next_page", f"看第 {page} 頁搜尋結果", browser)
                else:
                    browser.scroll_more()
                    yield step(site, "next_page", "往下捲動，載入更多搜尋結果", browser)
                results_url = browser.url()
                # 往下捲動的網站會保留舊卡片：先多讀看過的張數，排除看過的之後才取 MAX_CARDS 張
                cards = result_cards(site, browser.result_cards(), limit=len(seen) + MAX_CARDS)
                if not [c for c in cards if c.url not in seen]:
                    return  # 沒有更多結果了
                continue
            picked, source = decider.pick_candidates(site, plan, fresh, k=min(len(fresh), (quota - taken) * 2))
            seen.update(c.url for c in fresh)  # 這一頁模型沒挑的就是不值得看，不再重挑
            yield decision(site, "pick", "先看：" + "、".join(c.name for c in picked), source)
            outcome = yield from visit_cards(browser, site, picked, quota, taken, results_url)
            if outcome == "blocked":
                return
            taken = sum(1 for c in candidates if c.site == site.id)
            if taken >= quota or len(candidates) >= prep.max_candidates or stopped():
                return

    def visit_cards(browser: SourcingBrowser, site: Site, picked: list, quota: int, taken: int,
                    results_url: str) -> Generator[dict, None, str]:
        """3. 逐一讀個人頁：Jev 點擊，沒點到就直接點連結；gpt-6-luna 讀完判斷符不符合。

        回傳 "blocked" 表示網站跳出機器人驗證，這個網站要整個停下。"""
        for card in picked:
            if taken >= quota or len(candidates) >= prep.max_candidates or stopped():
                return
            if blocked_reason(card.url):
                continue
            card_geometry = browser_call(browser, "card_box", card.url)
            if browser.jev_ready and browser_call(browser, "visible_link", card.url) is not False:
                goal = f"Open the profile page of {card.name}: click the link that goes to {card.url}."
                for jev in browser.jev_goal(goal, site.domains, max_steps=3):
                    yield jev_step(site, jev, browser)
            if not _same_page(browser.url(), card.url):
                how = browser.click_link(card.url)
                geometry = getattr(browser, "last_click", None) or card_geometry
                if geometry and card_geometry:
                    geometry = {**geometry, "box": card_geometry["box"]}  # 方框用整張候選人卡片
                yield step(site, "open_profile", f"{'點擊' if how == 'click' else '開啟'}個人頁：{card.name}",
                           browser, geometry=geometry)
            if browser.challenge():
                yield {"type": "site_error", "site": site.id, "reason": "個人頁顯示機器人驗證，停止這個網站"}
                return "blocked"
            cand = summarize(site, card.url, browser.title(), browser.text(), browser.links(), plan,
                             fallback_name=card.name)
            if plan.terms.location and not site.location_filter:
                cand.location_note = f"此網站無法依地點篩選，不一定在{location_label(plan.terms.location)}"
            if cand.fit == "不符合":
                yield {"type": "candidate_skipped", "site": site.id, "name": cand.name, "reason": cand.fit_reason}
            else:
                candidates.append(cand)
                taken += 1
                event = {"type": "candidate", "candidate": cand.as_dict()}
                handle = card.url.rstrip("/").rsplit("/", 1)[-1]
                box = browser_call(browser, "name_box", card.name, handle, cand.name)
                if box:
                    event["geometry"] = box  # 個人頁上名字的位置，前端可以跟這筆紀錄一起亮起來
                yield event
            browser.back()
            if not _same_page(browser.url(), results_url):
                browser.open(results_url)
        return "ok"

    try:
        with browser_factory() as browser:
            if not browser.jev_ready:
                yield {"type": "notice", "message": "未設定 OPENROUTER_API_KEY：改用確定性操作（不經 Jev），需求與摘要改用規則版。"}
            for site, group_left in _site_order(browser_sites, bool(plan.terms.location)):
                remaining = prep.max_candidates - len(candidates)
                if remaining <= 0 or stopped():
                    break
                unlocated = [s for s in browser_sites if not s.location_filter]
                if plan.terms.location and unlocated and site is unlocated[0]:
                    lead = ("能依地點篩選的網站找到的人不夠，改用 " if len(unlocated) < len(browser_sites)
                            else "改用 ")
                    yield {"type": "notice", "message": f"{lead}{'、'.join(s.name for s in unlocated)} 補足；"
                                                        f"這些網站無法依地點篩選，找到的人不一定在"
                                                        f"{location_label(plan.terms.location)}。"}
                quota = math.ceil(remaining / group_left)
                try:
                    yield from search_site(browser, site, quota)
                except Exception as exc:  # 一個網站出錯不影響其他網站，例如 ORCID 頁面卡住造成 WebSocket 逾時
                    yield {"type": "site_error", "site": site.id,
                           "reason": f"{site.name} 發生錯誤（{type(exc).__name__}），已跳過這個網站"}
                    try:
                        browser.open("about:blank")
                    except Exception:
                        yield {"type": "error", "reason": "瀏覽器已無法使用，停止其餘網站"}
                        break
    except BrowserUnavailable as exc:
        yield from fill_nearby()
        yield {"type": "error", "reason": str(exc)}
        return

    yield from fill_nearby()
    yield {"type": "done", "count": len(candidates), "plan": plan.as_dict(), "message": DONE_MESSAGE,
               "usage": prep.usage.as_dict(), "cancelled": stopped()}


def _site_order(sites: list[Site], has_location: bool) -> Iterator[tuple[Site, int]]:
    """瀏覽器網站的順序與分配：(網站, 這一組含自己還剩幾個網站)。

    指定地點時，能依地點篩選的網站（GitHub）先跑並分掉全部名額；不能篩地點的網站
    （Hugging Face、Kaggle、Dribbble）只補不足的部分。沒指定地點就照原順序平分。"""
    groups = ([[s for s in sites if s.location_filter], [s for s in sites if not s.location_filter]]
              if has_location else [list(sites)])
    for group in groups:
        for i, site in enumerate(group):
            yield site, len(group) - i


def location_label(location: str) -> str:
    """英文地名換回中文給 HR 看（Taichung → 台中），沒有對照就用原文。"""
    return next((zh for zh, en in planner.LOCATIONS.items() if en == location), location)


_IDLE = object()


def stream_live(prep: Prepared, *, fps: float = 6.0,
                browser_factory: Optional[Callable[[], SourcingBrowser]] = None) -> Iterator[dict]:
    """在 stream() 的事件之間穿插 Chrome 的即時畫面（frame 事件，每秒最多 fps 張）。

    找人流程在背景執行緒跑；前端斷線時這個產生器會被關閉，設定 stop 讓背景流程在下一步停下並關掉 Chrome。
    """
    factory = browser_factory or (lambda: SourcingBrowser(screencast=True))
    holder: dict[str, Any] = {}
    events: "queue.Queue[Any]" = queue.Queue()
    stop = threading.Event()

    def make() -> SourcingBrowser:
        holder["browser"] = factory()
        return holder["browser"]

    def work() -> None:
        try:
            for event in stream(prep, browser_factory=make, stop=stop):
                events.put(event)
        except Exception as exc:  # 背景執行緒的例外要回報給前端，不能靜靜消失
            events.put({"type": "error", "reason": f"找人流程中斷：{type(exc).__name__}"})
        finally:
            events.put(None)

    threading.Thread(target=work, name="sourcing-run", daemon=True).start()
    interval = 1.0 / max(fps, 0.5)
    last_seq, last_sent = 0, 0.0
    try:
        while True:
            try:
                event = events.get(timeout=interval)
            except queue.Empty:
                event = _IDLE
            if event is None:
                break
            if event is not _IDLE:
                yield event
            latest = getattr(holder.get("browser"), "latest_frame", None)
            if latest is None:
                continue
            seq, data = latest()
            now = time.monotonic()
            if data and seq != last_seq and now - last_sent >= interval:
                last_seq, last_sent = seq, now
                yield {"type": "frame", "data": "data:image/jpeg;base64," + data}
    finally:
        stop.set()
