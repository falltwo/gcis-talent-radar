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
from typing import Any, Callable, Iterator, Optional

from agent.audit_log import write_agent_audit
from agent.prompt_guard import inspect_hiring_prompt
from sourcing import decider, planner
from sourcing.browser import BrowserUnavailable, SourcingBrowser
from sourcing.extract import Candidate, from_openalex, from_stackoverflow_api, result_cards, summarize
from sourcing.sites import Site, blocked_reason, sites_for

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
    if not prep.runnable:
        yield prep.final_event
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
        event = {"type": "step", "n": step_no, "site": site.id, "action": action, "detail": detail,
                 "url": browser.url() if browser else extra.pop("url", ""), **extra}
        if prep.screenshots and browser is not None:
            try:
                event["screenshot"] = browser.screenshot()
            except Exception:
                event["screenshot"] = None
        return event

    def decision(site: Site, what: str, detail: str, source: str) -> dict:
        return {"type": "decision", "site": site.id, "what": what, "detail": detail,
                "by": "gpt-6-luna" if source == "llm" else "rules"}

    # 只走官方 API 的網站（OpenAlex）先跑，不需要開瀏覽器
    api_sites = [s for s in prep.sites if s.search_url is None]
    browser_sites = [s for s in prep.sites if s.search_url is not None]
    for i, site in enumerate(api_sites):
        remaining = prep.max_candidates - len(candidates)
        if remaining <= 0 or stopped():
            break
        quota = math.ceil(remaining / (len(prep.sites) - i))
        yield step(site, "read_api", f"用 OpenAlex 官方 API 搜尋論文作者：{plan.terms.text()}",
                   url="https://api.openalex.org", screenshot=None)
        found = from_openalex(site, plan, limit=quota)
        if found is None:
            yield {"type": "site_error", "site": site.id, "reason": "OpenAlex API 暫時無法使用"}
            continue
        if not found:
            yield {"type": "site_error", "site": site.id, "reason": "OpenAlex 沒有找到符合地點的作者"}
        for cand in found:
            candidates.append(cand)
            yield {"type": "candidate", "candidate": cand.as_dict()}
    if not browser_sites or len(candidates) >= prep.max_candidates or stopped():
        yield {"type": "done", "count": len(candidates), "plan": plan.as_dict(), "message": DONE_MESSAGE}
        return

    try:
        with browser_factory() as browser:
            if not browser.jev_ready:
                yield {"type": "notice", "message": "未設定 OPENROUTER_API_KEY：改用確定性操作（不經 Jev），需求與摘要改用規則版。"}
            for i, site in enumerate(browser_sites):
                remaining = prep.max_candidates - len(candidates)
                if remaining <= 0 or stopped():
                    break
                quota = math.ceil(remaining / (len(browser_sites) - i))
                search_url = site.search_url(plan.terms)

                # 1. 搜尋：gpt-6-luna 決定要打的字，Jev 在入口頁的搜尋框操作；沒完成就直接開搜尋結果頁
                searched = False
                try:
                    if browser.jev_ready and site.entry_url:
                        text, source = decider.search_text(site, plan)
                        yield decision(site, "search_text", f"在 {site.name} 搜尋：{text}", source)
                        browser.open(site.entry_url)
                        yield step(site, "open_entry", f"開啟 {site.name}", browser)
                        goal = (f"Search this website for: {text}. Click the main search box, type the text, and press "
                                "Enter, until the search results are shown. Do not sign in.")
                        for jev in browser.jev_goal(goal, site.domains, text=text, entry_url=site.entry_url):
                            yield step(site, f"jev_{jev['action']}", jev["detail"], browser, confidence=jev["confidence"])
                            if stopped():
                                break
                        searched = bool(result_cards(site, browser.result_cards()))
                        if not searched:
                            yield step(site, "fallback", f"Jev 沒有完成搜尋（{browser.last_outcome}），改直接開搜尋結果頁")
                    if not searched:
                        browser.open(search_url)
                        yield step(site, "open_search", f"在 {site.name} 搜尋：{plan.terms.text()}", browser)
                except PermissionError as exc:
                    yield {"type": "site_error", "site": site.id, "reason": str(exc)}
                    continue
                reason = browser.challenge()
                if reason:
                    yield {"type": "site_error", "site": site.id, "reason": reason}
                    continue
                if not searched:
                    for jev in browser.jev_goal(POPUP_GOAL, site.domains, max_steps=3):
                        yield step(site, f"jev_{jev['action']}", jev["detail"], browser, confidence=jev["confidence"])

                # 2. 挑人：gpt-6-luna 從搜尋結果卡片挑出最值得看的幾位
                cards = result_cards(site, browser.result_cards())
                if not cards:
                    yield {"type": "site_error", "site": site.id, "reason": "搜尋結果頁沒有找到候選人連結"}
                    continue
                picked, source = decider.pick_candidates(site, plan, cards, k=min(len(cards), quota * 2))
                yield decision(site, "pick", "先看：" + "、".join(c.name for c in picked), source)
                results_url = browser.url()

                # 3. 逐一點進個人頁：Jev 點擊，沒點到就直接點連結；gpt-6-luna 讀完判斷符不符合
                taken = 0
                for card in picked:
                    if taken >= quota or len(candidates) >= prep.max_candidates or stopped():
                        break
                    if blocked_reason(card.url):
                        continue
                    if site.profile_api == "stackexchange":
                        cand = from_stackoverflow_api(site, card.url, plan, fallback_name=card.name)
                        yield step(site, "read_api", f"用 Stack Exchange 官方 API 讀取：{card.name}", browser)
                        if cand is None:
                            yield {"type": "site_error", "site": site.id, "reason": "Stack Exchange API 暫時無法使用"}
                            break
                        candidates.append(cand)
                        taken += 1
                        yield {"type": "candidate", "candidate": cand.as_dict()}
                        continue
                    if browser.jev_ready:
                        goal = f"Open the profile page of {card.name}: click the link that goes to {card.url}."
                        for jev in browser.jev_goal(goal, site.domains, max_steps=3):
                            yield step(site, f"jev_{jev['action']}", jev["detail"], browser, confidence=jev["confidence"])
                    if not _same_page(browser.url(), card.url):
                        how = browser.click_link(card.url)
                        yield step(site, "open_profile", f"{'點擊' if how == 'click' else '開啟'}個人頁：{card.name}", browser)
                    if browser.challenge():
                        yield {"type": "site_error", "site": site.id, "reason": "個人頁顯示機器人驗證，停止這個網站"}
                        break
                    cand = summarize(site, card.url, browser.title(), browser.text(), browser.links(), plan,
                                     fallback_name=card.name)
                    if cand.fit == "不符合":
                        yield {"type": "candidate_skipped", "site": site.id, "name": cand.name, "reason": cand.fit_reason}
                    else:
                        candidates.append(cand)
                        taken += 1
                        yield {"type": "candidate", "candidate": cand.as_dict()}
                    browser.back()
                    if not _same_page(browser.url(), results_url):
                        browser.open(results_url)
    except BrowserUnavailable as exc:
        yield {"type": "error", "reason": str(exc)}
        return

    yield {"type": "done", "count": len(candidates), "plan": plan.as_dict(), "message": DONE_MESSAGE}


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
