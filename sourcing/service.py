"""找人流程：守門 → 規劃 → 依職類挑網站 → computer use 搜尋與開個人頁 → 整理摘要。

`prepare()` 先做不需要瀏覽器的檢查並寫稽核紀錄；`stream()` 再一步一步產生事件給前端。
事件型別：plan、site_skipped、step、candidate、site_error、error、done，另外 prepare 可能直接給
rejected 或 no_public_work。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional

from agent.audit_log import write_agent_audit
from agent.prompt_guard import inspect_hiring_prompt
from sourcing import planner
from sourcing.browser import BrowserUnavailable, SourcingBrowser
from sourcing.extract import Candidate, from_openalex, from_stackoverflow_api, profile_links, summarize
from sourcing.sites import Site, blocked_reason, sites_for

DONE_MESSAGE = "只列出公開頁面的連結，未蒐集 Email 或電話；聯絡前請自行確認候選人的公開意願。"
JEV_GOAL = ("Close any cookie banner, sign-in prompt or popup so that the list of search results "
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


def stream(prep: Prepared, *, browser_factory: Optional[Callable[[], SourcingBrowser]] = None) -> Iterator[dict]:
    browser_factory = browser_factory or SourcingBrowser
    if not prep.runnable:
        yield prep.final_event
        return
    plan = prep.plan
    yield {"type": "plan", "plan": plan.as_dict(), "sites": [{"id": s.id, "name": s.name} for s in prep.sites]}
    for s in prep.skipped:
        yield {"type": "site_skipped", "site": s.id, "name": s.name, "reason": s.unavailable_reason}

    candidates: list[Candidate] = []
    step_no = 0

    def step(site: Site, action: str, detail: str, browser: SourcingBrowser, **extra: Any) -> dict:
        nonlocal step_no
        step_no += 1
        event = {"type": "step", "n": step_no, "site": site.id, "action": action, "detail": detail,
                 "url": browser.url(), **extra}
        if prep.screenshots:
            try:
                event["screenshot"] = browser.screenshot()
            except Exception:
                event["screenshot"] = None
        return event

    # 只走官方 API 的網站（OpenAlex）先跑，不需要開瀏覽器
    api_sites = [s for s in prep.sites if s.search_url is None]
    browser_sites = [s for s in prep.sites if s.search_url is not None]
    for i, site in enumerate(api_sites):
        remaining = prep.max_candidates - len(candidates)
        if remaining <= 0:
            break
        quota = math.ceil(remaining / (len(prep.sites) - i))
        step_no += 1
        yield {"type": "step", "n": step_no, "site": site.id, "action": "read_api", "url": "https://api.openalex.org",
               "detail": f"用 OpenAlex 官方 API 搜尋論文作者：{plan.terms.text()}", "screenshot": None}
        found = from_openalex(site, plan, limit=quota)
        if found is None:
            yield {"type": "site_error", "site": site.id, "reason": "OpenAlex API 暫時無法使用"}
            continue
        if not found:
            yield {"type": "site_error", "site": site.id, "reason": "OpenAlex 沒有找到符合地點的作者"}
        for cand in found:
            candidates.append(cand)
            yield {"type": "candidate", "candidate": cand.as_dict()}
    if not browser_sites or len(candidates) >= prep.max_candidates:
        yield {"type": "done", "count": len(candidates), "plan": plan.as_dict(), "message": DONE_MESSAGE}
        return

    try:
        with browser_factory() as browser:
            if not browser.jev_ready:
                yield {"type": "notice", "message": "未設定 OPENROUTER_API_KEY：Jev 不會處理彈窗，摘要改用規則版。"}
            for i, site in enumerate(browser_sites):
                remaining = prep.max_candidates - len(candidates)
                if remaining <= 0:
                    break
                quota = math.ceil(remaining / (len(browser_sites) - i))
                search_url = site.search_url(plan.terms)
                try:
                    browser.open(search_url)
                except PermissionError as exc:
                    yield {"type": "site_error", "site": site.id, "reason": str(exc)}
                    continue
                yield step(site, "open_search", f"在 {site.name} 搜尋：{plan.terms.text()}", browser)
                reason = browser.challenge()
                if reason:
                    yield {"type": "site_error", "site": site.id, "reason": reason}
                    continue
                for jev in browser.jev_steps(JEV_GOAL, site.domains):
                    yield step(site, f"jev_{jev['action']}", jev["detail"], browser, confidence=jev["confidence"])

                found = profile_links(site, browser.links())
                if not found:
                    yield {"type": "site_error", "site": site.id, "reason": "搜尋結果頁沒有找到候選人連結"}
                    continue
                taken = 0
                for profile in found:
                    if taken >= quota or len(candidates) >= prep.max_candidates:
                        break
                    if blocked_reason(profile.href):
                        continue
                    if site.profile_api == "stackexchange":
                        cand = from_stackoverflow_api(site, profile.href, plan, fallback_name=profile.text)
                        yield step(site, "read_api", f"用 Stack Exchange 官方 API 讀取：{profile.text or profile.href}", browser)
                        if cand is None:
                            yield {"type": "site_error", "site": site.id, "reason": "Stack Exchange API 暫時無法使用"}
                            break
                        candidates.append(cand)
                        taken += 1
                        yield {"type": "candidate", "candidate": cand.as_dict()}
                        continue
                    how = browser.click_link(profile.href)
                    yield step(site, "open_profile", f"{'點擊' if how == 'click' else '開啟'}個人頁：{profile.text or profile.href}",
                               browser)
                    if browser.challenge():
                        yield {"type": "site_error", "site": site.id, "reason": "個人頁顯示機器人驗證，停止這個網站"}
                        break
                    cand = summarize(site, profile.href, browser.title(), browser.text(), browser.links(), plan,
                                     fallback_name=profile.text)
                    candidates.append(cand)
                    taken += 1
                    yield {"type": "candidate", "candidate": cand.as_dict()}
                    browser.open(search_url) if how == "navigate" else browser.back()
    except BrowserUnavailable as exc:
        yield {"type": "error", "reason": str(exc)}
        return

    yield {"type": "done", "count": len(candidates), "plan": plan.as_dict(), "message": DONE_MESSAGE}
