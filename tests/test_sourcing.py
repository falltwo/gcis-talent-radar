"""找人 agent：網站目錄、需求規劃、擷取、流程與 SSE API。瀏覽器一律用假的，不連網。"""
import asyncio
import json
import os

import pytest

from api.main import app
from sourcing import apis, extract, llm, planner, service
from sourcing.extract import Link
from sourcing.sites import SITES, SearchTerms, blocked_reason, catalog, sites_for


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(apis, "github_user_count", lambda q: 100)  # 不連 GitHub 官方 API
    return tmp_path


# ------------------------------------------------------------------ sites
def test_profile_urls_skip_reserved_paths_and_normalize():
    gh = SITES["github"]
    assert gh.profile_url("https://github.com/octocat/?tab=repositories") == "https://github.com/octocat"
    assert gh.profile_url("https://github.com/features") is None
    assert gh.profile_url("https://github.com/octocat/hello-world") is None
    so = SITES["stackoverflow"]
    assert so.profile_url("https://stackoverflow.com/users/22656/jon-skeet") == "https://stackoverflow.com/users/22656/jon-skeet"
    assert so.profile_url("https://stackoverflow.com/users/login") is None
    assert SITES["orcid"].profile_url("https://orcid.org/0000-0002-1694-233X") == "https://orcid.org/0000-0002-1694-233X"
    assert SITES["kaggle"].profile_url("https://www.kaggle.com/code") is None


def test_huggingface_model_links_point_back_to_author():
    hf = SITES["huggingface"]
    assert hf.profile_url("https://huggingface.co/google-bert/bert-base-chinese") == "https://huggingface.co/google-bert"
    assert hf.profile_url("https://huggingface.co/models/foo") is None


def test_blocked_domains_include_subdomains():
    assert blocked_reason("https://tw.linkedin.com/in/someone")
    assert blocked_reason("https://scholar.google.com/citations?user=x")
    assert blocked_reason("https://www.104.com.tw/resume")
    assert blocked_reason("https://github.com/octocat") is None


def test_sites_follow_category_table_and_flag_unavailable():
    ids = {s.id for s in sites_for(["design"])}
    assert ids == {"dribbble", "behance"}
    by_id = {row["id"]: row for row in catalog()}
    assert by_id["gitlab"]["available"] is False and "Cloudflare" in by_id["gitlab"]["unavailable_reason"]
    assert by_id["behance"]["available"] is False
    assert by_id["personal"]["available"] is True
    assert {s.id for s in sites_for(["software"], only=["github"])} == {"github"}


def test_github_search_url_uses_language_and_location_qualifiers():
    url = SITES["github"].search_url(SearchTerms(("python", "django"), "Taichung"))
    assert "language%3Apython" in url and "django" in url and "location%3ATaichung" in url and url.endswith("type=users")


# ------------------------------------------------------------------ planner
def test_rule_plan_reads_role_skills_and_location():
    p = planner.rule_plan("找會 Python 和 Django 的後端工程師，在台中")
    assert p.categories == ["software"] and p.has_public_work
    assert p.terms.skills[:2] == ("python", "django") and p.terms.location == "Taichung"


def test_rule_plan_design_and_ai_roles():
    assert planner.rule_plan("UI 設計師").categories == ["design"]
    assert "ai_data" in planner.rule_plan("機器學習工程師").categories


def test_rule_plan_reads_english_role_right_next_to_chinese():
    p = planner.rule_plan("找AI工程師 在台中")
    assert "ai_data" in p.categories and p.terms.skills == ("ai",) and p.terms.location == "Taichung"
    assert planner.rule_plan("UI設計師").categories == ["design"]
    assert "ai_data" in planner.rule_plan("找ML工程師").categories


def test_rule_plan_does_not_match_skill_inside_other_words():
    assert "go" not in planner.rule_plan("google 背景的 Python 工程師").terms.skills


def test_roles_without_public_work_get_advice():
    p = planner.rule_plan("找 10 個作業員")
    assert not p.has_public_work and "其他管道" in p.notes[0]


def test_llm_plan_filters_personal_traits_and_unknown_categories(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {
        "categories": ["software", "cooking"], "skills": ["Python", "female", "fastapi"],
        "location": "Taichung", "has_public_work": True})
    p = planner.plan("後端工程師")
    assert p.source == "llm" and p.categories == ["software"]
    assert p.terms.skills == ("python", "fastapi")


def test_llm_failure_falls_back_to_rules(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: None)
    p = planner.plan("Python 工程師")
    assert p.source == "rules" and p.categories == ["software"]


# ------------------------------------------------------------------ extract
def test_clean_text_removes_contact_details_and_bad_surrogates():
    out = extract.clean_text("mail me: a.b@example.com or 0912-345-678 \ud83c")
    assert "@" not in out and "0912" not in out and "\ud83c" not in out


def test_profile_work_and_personal_site_links():
    gh = SITES["github"]
    links = [Link("https://github.com/alice", "Alice"), Link("https://github.com/alice?tab=x", "dup"),
             Link("https://github.com/pricing", "Pricing"), Link("https://github.com/bob", "Bob")]
    assert [l.href for l in extract.profile_links(gh, links)] == ["https://github.com/alice", "https://github.com/bob"]
    page = [Link("https://github.com/alice/alice", "alice"), Link("https://github.com/alice/radar", "radar"),
            Link("https://github.com/alice/followers"),
            Link("https://twitter.com/alice", rel="me"), Link("https://tw.linkedin.com/in/a", rel="me"),
            Link("https://alice.dev/", rel="nofollow me")]
    assert [w.href for w in extract.work_links(gh, "https://github.com/alice", page)] == ["https://github.com/alice/radar"]
    assert extract.personal_site(gh, page) == "https://alice.dev/"


def test_summary_without_model_uses_page_facts_only():
    plan = planner.rule_plan("Python 工程師")
    cand = extract.summarize(SITES["github"], "https://github.com/alice", "alice (Alice Chen) · GitHub",
                             ["Backend developer who loves Python and APIs", "contact: alice@example.com"],
                             [Link("https://github.com/alice/api-kit", "api-kit")], plan, fallback_name="Alice Chen")
    assert cand.name == "Alice Chen" and cand.matched_skills == ["python"] and cand.summary_source == "rules"
    assert cand.evidence[0] == {"label": "個人頁", "url": "https://github.com/alice"}
    assert "@" not in json.dumps(cand.as_dict(), ensure_ascii=False)


# ------------------------------------------------------------------ service
def _page_key(url):
    """搜尋結果頁去掉搜尋字（q、search 參數），只留網站、路徑與頁碼。"""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    parts = urlsplit(url)
    params = parse_qsl(parts.query)
    query = [(k, v) for k, v in params if k not in ("q", "search")]
    if len(query) < len(params):
        query.append(("_searched", "1"))  # 入口頁（沒有搜尋字）和搜尋結果頁要分開
    return urlunsplit(parts._replace(query=urlencode(query)))


class _Pages(dict):
    def get(self, url, default=None):
        return super().get(url) or super().get(_page_key(url), default)


class FakeBrowser:
    """模擬搜尋結果頁與個人頁；記錄開過的網址。"""

    def __init__(self, pages, *, challenge_on=()):
        self.pages = _Pages({**pages, **{_page_key(u): v for u, v in pages.items()}})
        self.challenge_on = set(challenge_on)
        self.current = "about:blank"
        self.history = []
        self.opened = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    jev_ready = False

    def open(self, url):
        reason = blocked_reason(url)
        if reason:
            raise PermissionError(reason)
        self.history.append(self.current)
        self.current = url
        self.opened.append(url)

    def back(self):
        self.current = self.history.pop()

    def click_link(self, href):
        self.open(href)
        return "click"

    def url(self):
        return self.current

    def title(self):
        return self.pages.get(self.current, {}).get("title", "")

    def text(self, limit=80):
        return self.pages.get(self.current, {}).get("text", [])

    def links(self):
        return [Link(h, t) for h, t in self.pages.get(self.current, {}).get("links", [])]

    def result_cards(self):
        return [(h, t, f"{t} card text") for h, t in self.pages.get(self.current, {}).get("links", [])]

    def screenshot(self):
        return "data:image/jpeg;base64,AAAA"

    def challenge(self):
        return "驗證頁" if any(self.current.startswith(p) for p in self.challenge_on) else None

    last_outcome = "skipped"

    def jev_goal(self, goal, domains, **kw):
        return iter(())


def _github_pages():
    search = SITES["github"].search_url(SearchTerms(("python",), None))
    pages = {search: {"title": "search", "links": [
        ("https://github.com/features", ""), ("https://github.com/alice", "Alice"),
        ("https://github.com/bob", "Bob"), ("https://github.com/carol", "Carol")]}}
    for name in ("alice", "bob", "carol"):
        pages[f"https://github.com/{name}"] = {"title": f"{name} · GitHub",
                                               "text": [f"{name} writes Python", f"{name}@mail.com"],
                                               "links": [(f"https://github.com/{name}/proj", "proj")]}
    return pages


def test_prepare_rejects_protected_trait_filters(isolated):
    prep = service.prepare("找 30 歲以下的 Python 工程師")
    assert prep.final_event["type"] == "rejected"
    audit = (isolated / "audit.jsonl").read_text(encoding="utf-8")
    assert "SOURCING_REJECTED_FAIR_HIRING" in audit and "Python" not in audit  # 只存雜湊


def test_prepare_no_public_work_skips_browser():
    prep = service.prepare("找倉管人員")
    events = list(service.stream(prep, browser_factory=lambda: pytest.fail("不應開瀏覽器")))
    assert [e["type"] for e in events] == ["no_public_work"]


def test_stream_collects_candidates_up_to_limit_with_screenshots():
    prep = service.prepare("Python 工程師", max_candidates=2, site_ids=["github"])
    browser = FakeBrowser(_github_pages())
    events = list(service.stream(prep, browser_factory=lambda: browser))
    types = [e["type"] for e in events]
    assert types[0] == "plan" and types[-1] == "done" and types.count("candidate") == 2
    assert all(e["screenshot"] for e in events if e["type"] == "step")
    cands = [e["candidate"] for e in events if e["type"] == "candidate"]
    assert [c["profile_url"] for c in cands] == ["https://github.com/alice", "https://github.com/bob"]
    assert "@" not in json.dumps(cands, ensure_ascii=False)
    assert "https://github.com/features" not in browser.opened


def test_stream_skips_site_behind_bot_check():
    prep = service.prepare("Python 工程師", site_ids=["github"])
    browser = FakeBrowser(_github_pages(), challenge_on=["https://github.com/search"])
    events = list(service.stream(prep, browser_factory=lambda: browser))
    assert any(e["type"] == "site_error" and "驗證" in e["reason"] for e in events)
    assert not any(e["type"] == "candidate" for e in events)


def test_stream_reports_unavailable_sites_without_visiting():
    prep = service.prepare("UI 設計師")
    browser = FakeBrowser({})
    events = list(service.stream(prep, browser_factory=lambda: browser))
    skipped = [e for e in events if e["type"] == "site_skipped"]
    assert [e["site"] for e in skipped] == ["behance"]
    assert not any("behance" in u for u in browser.opened)


def test_stream_turns_missing_browser_into_error_event():
    prep = service.prepare("Python 工程師", site_ids=["github"])

    def broken():
        raise service.BrowserUnavailable("尚未安裝 typesafe-computer-use")

    events = list(service.stream(prep, browser_factory=broken))
    assert events[-1] == {"type": "error", "reason": "尚未安裝 typesafe-computer-use"}


# ------------------------------------------------------------------ API
def _post(path, body):
    messages = []

    async def exchange():
        payload = json.dumps(body).encode()
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": payload, "more_body": False}
            await asyncio.Event().wait()  # 串流期間用戶端保持連線

        async def send(message):
            messages.append(message)

        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
                   "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
                   "headers": [(b"content-type", b"application/json")], "client": ("test", 1), "server": ("test", 80)},
                  receive, send)

    asyncio.run(exchange())
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body").decode()
    return status, body


def test_search_endpoint_streams_server_sent_events(monkeypatch):
    browser = FakeBrowser(_github_pages())
    monkeypatch.setattr(service, "SourcingBrowser", lambda **kw: browser)
    status, body = _post("/api/sourcing/search", {"query": "Python 工程師", "max_candidates": 1, "sites": ["github"]})
    assert status == 200
    frames = [f for f in body.split("\n\n") if f.strip()]
    names = [f.split("\n")[0].removeprefix("event: ") for f in frames]
    assert names[0] == "plan" and names[-1] == "done" and "candidate" in names
    done = json.loads(frames[-1].split("\n", 1)[1].removeprefix("data: "))
    assert done["count"] == 1


def test_search_endpoint_validates_input():
    status, _ = _post("/api/sourcing/search", {"query": "x"})
    assert status == 422


# ------------------------------------------------------------------ Jev 迴圈（假的 Chrome 與 Jev）
from types import SimpleNamespace

from sourcing.browser import SourcingBrowser


class _Act:
    def __init__(self, session):
        self.session, self.calls = session, []

    def click(self, session, index, element, page):
        self.calls.append(("click", index))
        session.href = element.href or session.href
        return f"clicked {index}"

    def press(self, session, key):
        self.calls.append(("press", key))
        return key

    def scroll(self, session, lines, page):
        self.calls.append(("scroll", lines))
        return "scrolled"

    def go_back(self, session):
        self.calls.append(("back",))
        session.href = session.previous

    def wait_for_load(self, session):
        pass


def _jev_browser(decisions, items):
    session = SimpleNamespace(href="https://orcid.org/search", previous="https://orcid.org/search")
    session.evaluate = lambda expr: "complete" if expr == "document.readyState" else session.href
    b = SourcingBrowser()
    b._client, b._session = object(), session
    b._act = _Act(session)
    b._perceive = lambda s: SimpleNamespace(items=items, text=[])
    queue = list(decisions)
    b._decide = lambda *a, **k: queue.pop(0)
    return b


def _decision(kind, element=None, confidence=0.9, satisfied=0.0):
    return SimpleNamespace(kind=SimpleNamespace(choice=kind), chosen_element=element, confidence=confidence,
                           satisfied=SimpleNamespace(noul=satisfied))


def test_jev_dismisses_banner_then_stops_when_done(monkeypatch):
    monkeypatch.setattr("sourcing.browser.time.sleep", lambda s: None)
    accept = SimpleNamespace(index=3, href="", name="Accept cookies", tag="button", in_view=True, covered=False)
    b = _jev_browser([_decision("click", 3), _decision("done", satisfied=0.9)], [accept])
    steps = list(b.jev_goal("close banner", ("orcid.org",)))
    assert [s["action"] for s in steps] == ["click", "done"] and b.last_outcome == "done"
    assert b._act.calls == [("click", 3)]


def test_jev_cannot_type_or_leave_allowed_domain(monkeypatch):
    monkeypatch.setattr("sourcing.browser.time.sleep", lambda s: None)
    outside = SimpleNamespace(index=1, href="https://evil.example/login", in_view=True, covered=False)
    b = _jev_browser([_decision("click", 1)], [outside])
    steps = list(b.jev_goal("x", ("orcid.org",)))
    assert steps[0]["action"] == "refused" and b._act.calls == []


def test_jev_low_confidence_stops_and_missing_key_skips():
    b = _jev_browser([_decision("press_escape", confidence=0.2), _decision("done")], [])
    steps = list(b.jev_goal("x", ("orcid.org",)))
    assert len(steps) == 1 and steps[0]["action"] == "press_escape" and b.last_outcome == "low_confidence"
    b._client = None
    assert list(b.jev_goal("x", ("orcid.org",))) == []


# ------------------------------------------------------------------ OpenAlex（取代 Google Scholar）
from sourcing import apis


def test_openalex_keeps_only_authors_from_target_city(monkeypatch):
    def fake(path, params, timeout):
        if path == "institutions":
            return {"meta": {"count": 2}, "results": [
                {"id": "https://openalex.org/I1", "geo": {"city": "Taichung"}},
                {"id": "https://openalex.org/I2", "geo": {"city": "Taipei"}}]}
        if path == "works":
            assert "authorships.institutions.id:I1" in params["filter"]
            return {"results": [{"id": "W1", "title": "Deep nets", "doi": "https://doi.org/10.1/x", "publication_year": 2024,
                                 "authorships": [
                                     {"author": {"id": "https://openalex.org/A9"}, "institutions": [{"id": "https://openalex.org/I2"}]},
                                     {"author": {"id": "https://openalex.org/A1"}, "institutions": [{"id": "https://openalex.org/I1"}]}]}]}
        assert params["filter"] == "openalex:A1"
        return {"results": [{"id": "https://openalex.org/A1", "display_name": "Lin", "orcid": "https://orcid.org/0000-0001-2345-6789",
                             "works_count": 40, "cited_by_count": 900,
                             "last_known_institutions": [{"id": "https://openalex.org/I1",
                                                          "display_name": "National Chung Hsing University"}],
                             "topics": [{"display_name": "Machine Learning"}]}]}

    monkeypatch.setattr(apis, "_openalex", fake)
    authors = apis.openalex_authors("machine learning", "Taichung", limit=3)
    assert [a["id"] for a in authors] == ["A1"] and authors[0]["top_work"]["url"] == "https://doi.org/10.1/x"


def test_research_role_uses_openalex_without_opening_browser(monkeypatch):
    monkeypatch.setattr(apis, "openalex_authors", lambda topic, location, limit: [{
        "id": "A1", "display_name": "Lin", "orcid": "https://orcid.org/0000-0001-2345-6789", "works_count": 40,
        "cited_by_count": 900, "institution": "National Chung Hsing University", "topics": ["Machine Learning"],
        "top_work": {"title": "Deep nets", "url": "https://doi.org/10.1/x"}}])
    prep = service.prepare("找台中的機器學習研究員", site_ids=["openalex"])
    events = list(service.stream(prep, browser_factory=lambda: pytest.fail("不應開瀏覽器")))
    cand = next(e["candidate"] for e in events if e["type"] == "candidate")
    assert cand["profile_url"] == "https://openalex.org/authors/A1" and "被引用 900 次" in cand["headline"]
    assert [e["label"] for e in cand["evidence"]][:2] == ["OpenAlex 作者頁", "ORCID"]
    assert events[-1]["type"] == "done"


def test_openalex_failure_is_reported_and_other_sites_continue(monkeypatch):
    monkeypatch.setattr(apis, "openalex_authors", lambda *a, **k: None)
    pages = {SITES["kaggle"].search_url(SearchTerms(("machine learning",), None)): {
        "title": "k", "links": [("https://www.kaggle.com/alice", "Alice")]},
        "https://www.kaggle.com/alice": {"title": "Alice | Kaggle", "text": ["ML notebooks"], "links": []}}
    prep = service.prepare("找機器學習研究員", site_ids=["openalex", "kaggle"])
    browser = FakeBrowser(pages)
    events = list(service.stream(prep, browser_factory=lambda: browser))
    assert any(e["type"] == "site_error" and e["site"] == "openalex" for e in events)
    assert any("kaggle.com" in u for u in browser.opened)


def test_openalex_drops_authors_who_moved_away(monkeypatch):
    def fake(path, params, timeout):
        if path == "institutions":
            return {"meta": {"count": 1}, "results": [{"id": "https://openalex.org/I1", "geo": {"city": "Taichung"}}]}
        if path == "works":
            return {"results": [{"id": "W1", "title": "t", "authorships": [
                {"author": {"id": "https://openalex.org/A1"}, "institutions": [{"id": "https://openalex.org/I1"}]}]}]}
        return {"results": [{"id": "https://openalex.org/A1", "display_name": "Moved",
                             "last_known_institutions": [{"id": "https://openalex.org/I7", "display_name": "Abroad Univ"}]}]}

    monkeypatch.setattr(apis, "_openalex", fake)
    assert apis.openalex_authors("x", "Taichung") == []


# ------------------------------------------------------------------ Jev 操作搜尋＋gpt-6-luna 決策＋即時畫面
from sourcing import decider
from sourcing.extract import Candidate


class JevFakeBrowser(FakeBrowser):
    """jev_ready 的假瀏覽器：Jev 在入口頁「打字送出」後跳到搜尋結果頁。"""

    jev_ready = True

    def __init__(self, pages, *, jev_finishes=True):
        super().__init__(pages)
        self.jev_finishes = jev_finishes
        self.goals = []
        self.frames = 0

    def jev_goal(self, goal, domains, *, text=None, entry_url=None, **kw):
        self.goals.append((goal, text))
        if text is None:
            return iter(())
        if not self.jev_finishes:
            self.last_outcome = "stuck"
            return iter([{"action": "refused", "detail": "拒絕", "confidence": 0.5}])
        self.open(SITES["github"].search_url(SearchTerms(("python",), None)))
        self.last_outcome = "done"
        return iter([{"action": "type_text", "detail": f"輸入：{text}", "confidence": 0.9},
                     {"action": "press_enter", "detail": "enter", "confidence": 0.9}])

    def latest_frame(self):
        self.frames += 1
        return self.frames, "AAAA"


def _types(events):
    return [e["type"] + (":" + e["action"] if e["type"] == "step" else "") for e in events]


def test_jev_types_the_search_that_rules_decided_without_model():
    prep = service.prepare("Python 工程師", max_candidates=1, site_ids=["github"])
    browser = JevFakeBrowser(_github_pages())
    events = list(service.stream(prep, browser_factory=lambda: browser))
    kinds = _types(events)
    assert kinds[:5] == ["plan", "decision", "step:open_entry", "step:jev_type_text", "step:jev_press_enter"]
    search = next(e for e in events if e["type"] == "decision" and e["what"] == "search_text")
    assert search["by"] == "rules" and "type:user language:python location:Taichung" in search["detail"]
    assert browser.goals[0][1] == "type:user language:python location:Taichung"
    assert "step:open_search" not in kinds and kinds.count("candidate") == 1


def test_falls_back_to_search_url_when_jev_does_not_finish():
    prep = service.prepare("Python 工程師", max_candidates=1, site_ids=["github"])
    browser = JevFakeBrowser(_github_pages(), jev_finishes=False)
    kinds = _types(list(service.stream(prep, browser_factory=lambda: browser)))
    assert "step:fallback" in kinds and "step:open_search" in kinds and kinds.count("candidate") == 1


def test_model_judged_mismatch_is_skipped_and_not_counted(monkeypatch):
    def fake_summarize(site, url, *a, **k):
        fit = "不符合" if url.endswith("alice") else "符合"
        return Candidate(site.id, url, url.rsplit("/", 1)[-1], fit=fit, fit_reason="只有前端經驗" if fit == "不符合" else "")

    monkeypatch.setattr(service, "summarize", fake_summarize)
    prep = service.prepare("Python 工程師", max_candidates=1, site_ids=["github"])
    events = list(service.stream(prep, browser_factory=lambda: FakeBrowser(_github_pages())))
    skipped = [e for e in events if e["type"] == "candidate_skipped"]
    kept = [e["candidate"]["name"] for e in events if e["type"] == "candidate"]
    assert skipped[0]["name"] == "alice" and skipped[0]["reason"] == "只有前端經驗" and kept == ["bob"]


def test_stream_live_interleaves_frames_and_finishes():
    prep = service.prepare("Python 工程師", max_candidates=1, site_ids=["github"])
    browser = JevFakeBrowser(_github_pages())
    events = list(service.stream_live(prep, fps=50, browser_factory=lambda: browser))
    assert events[-1]["type"] == "done"
    assert any(e["type"] == "frame" and e["data"].startswith("data:image/jpeg;base64,") for e in events)


def test_decider_validates_model_output(monkeypatch):
    plan = planner.rule_plan("Python 工程師，在台中")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"language": "Python", "keyword": "backend"})
    assert decider.search_text(SITES["github"], plan)[:2] == ("type:user language:python backend location:Taichung", "llm")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"language": "cobol", "keyword": "male"})
    # 兩個都不合格（清單外的語言、個人特徵）：不採用模型，沿用規則判斷的 Python
    assert decider.search_text(SITES["github"], plan)[:2] == ("type:user language:python location:Taichung", "rules")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"query": "python django flask machine learning Taichung"})
    assert decider.search_text(SITES["kaggle"], plan)[1] == "rules"
    cards = [decider.Card(f"https://github.com/u{i}", f"u{i}") for i in range(5)]
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"picks": [3, 3, 99, 1]})
    picked, source = decider.pick_candidates(SITES["github"], plan, cards, k=2)
    assert [c.name for c in picked] == ["u3", "u1"] and source == "llm"


def test_github_search_loosens_until_enough_people(monkeypatch):
    """GitHub 每個條件都要同時符合：太嚴就依序放寬，並在決策說明列出每一步的人數。"""
    counts = {"language:python AI location:Taichung": 0, "AI location:Taichung": 40}
    monkeypatch.setattr(apis, "github_user_count", lambda q: counts.get(q, 186))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"language": "python", "keyword": "AI"})
    plan = planner.rule_plan("找AI工程師 在台中")
    text, source, note = decider.search_text(SITES["github"], plan, need=5)
    assert text == "type:user AI location:Taichung" and source == "llm"
    assert "（0 人）" in note and "（40 人）" in note
    counts["AI location:Taichung"] = 2
    assert decider.search_text(SITES["github"], plan, need=5)[0] == "type:user language:python location:Taichung"
    monkeypatch.setattr(apis, "github_user_count", lambda q: None)  # 官方 API 不能用：取中間寬度
    assert decider.search_text(SITES["github"], plan)[0] == "type:user AI location:Taichung"


def test_sites_without_location_search_use_short_queries():
    terms = SearchTerms(("python", "pytorch", "tensorflow", "machine learning"), "Taichung")
    assert SITES["kaggle"].typed_query(terms) == "python pytorch"
    assert "Taichung" not in SITES["dribbble"].search_url(terms)
    assert SITES["kaggle"].query_url("deep learning") == "https://www.kaggle.com/search?q=deep+learning"
    assert SITES["github"].query_url("type:user AI location:Taichung").endswith("q=AI+location%3ATaichung&type=users")


def test_jev_may_only_type_into_search_fields_and_enter_after_typing(monkeypatch):
    monkeypatch.setattr("sourcing.browser.time.sleep", lambda s: None)
    login = SimpleNamespace(index=1, href="", name="Username or email", field=True, secret=False, in_view=True, covered=False)
    box = SimpleNamespace(index=2, href="", name="Search GitHub", field=True, secret=False, in_view=True, covered=False)
    b = _jev_browser([_decision("press_enter"), _decision("type_text", 1), _decision("type_text", 2),
                      _decision("press_enter"), _decision("done")], [login, box])
    typed = []
    b._act.type_text = lambda session, index, text: typed.append((index, text))
    b._act.field_value = lambda session, index: ""
    steps = list(b.jev_goal("search", ("orcid.org",), text="python"))
    assert [s["action"] for s in steps] == ["refused", "refused"] and b.last_outcome == "stuck" and typed == []
    b = _jev_browser([_decision("type_text", 2), _decision("press_enter"), _decision("done")], [login, box])
    b._act.type_text = lambda session, index, text: typed.append((index, text))
    steps = list(b.jev_goal("search", ("orcid.org",), text="python"))
    assert [s["action"] for s in steps] == ["type_text", "press_enter", "done"] and typed == [(2, "python")]


def test_usage_is_metered_and_reported_in_done(monkeypatch):
    from sourcing import usage

    meter = usage.Usage()
    usage.bind(meter)
    jev = usage.MeteredJev(SimpleNamespace(system_one=lambda **kw: SimpleNamespace(usage=SimpleNamespace(input_tokens=5000, output_tokens=40))))
    jev.system_one(state=[], questions={})
    meter.add_luna(1000, 100, None)
    d = meter.as_dict()
    assert d["jev"]["calls"] == 1 and d["jev"]["input_tokens"] == 5000
    assert d["gpt_6_luna"]["cost_usd"] == pytest.approx((1000 * 0.10 + 100 * 0.50) / 1e6)
    assert d["total_tokens"] == 6140
    prep = service.prepare("Python 工程師", max_candidates=1, site_ids=["github"])
    done = list(service.stream(prep, browser_factory=lambda: FakeBrowser(_github_pages())))[-1]
    assert done["type"] == "done" and "total_cost_usd" in done["usage"]


# ------------------------------------------------------------------ 給前端的任務接口
import threading
import time as _time

from sourcing import runs


def _wait(run, timeout=5):
    deadline = _time.time() + timeout
    while not run.finished and _time.time() < deadline:
        _time.sleep(0.02)
    return run


class SlowBrowser(FakeBrowser):
    """開搜尋頁時卡住，直到測試放行；用來測同時上限與取消。"""

    def __init__(self, pages, gate):
        super().__init__(pages)
        self.gate = gate

    def open(self, url):
        self.gate.wait(5)
        super().open(url)


def test_run_finishes_in_background_and_replays_events():
    registry = runs.RunRegistry(browser_factory=lambda: FakeBrowser(_github_pages()))
    run = _wait(registry.start(service.prepare("Python 工程師", max_candidates=2, site_ids=["github"])))
    snap = run.snapshot()
    assert snap["status"] == "done" and len(snap["candidates"]) == 2 and snap["usage"] is not None
    events = list(runs.follow(run, frames=False))
    assert [i for i, _ in events] == list(range(1, len(run.events) + 1))
    resumed = list(runs.follow(run, after=3, frames=False))
    assert resumed[0][0] == 4 and resumed[-1][1]["type"] == "done"


def test_rejected_request_creates_finished_run_without_browser():
    registry = runs.RunRegistry(browser_factory=lambda: pytest.fail("不應開瀏覽器"))
    run = registry.start(service.prepare("只找女生的設計師"))
    assert run.status == "rejected" and run.snapshot()["message"]


def test_concurrency_limit_and_cancel():
    gate = threading.Event()
    registry = runs.RunRegistry(max_running=1, browser_factory=lambda: SlowBrowser(_github_pages(), gate))
    first = registry.start(service.prepare("Python 工程師", site_ids=["github"]))
    with pytest.raises(runs.RunnerBusy):
        registry.start(service.prepare("Python 工程師", site_ids=["github"]))
    registry.cancel(first.id)
    gate.set()
    assert _wait(first).status == "cancelled" and first.events[-1].get("cancelled") is True
    second = _wait(registry.start(service.prepare("Python 工程師", max_candidates=1, site_ids=["github"])))
    assert second.status == "done"


def _request(method, path, body=None, headers=()):
    messages = []

    async def exchange():
        payload = json.dumps(body).encode() if body is not None else b""
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": payload, "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            messages.append(message)

        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                   "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"frames=false",
                   "headers": [(b"content-type", b"application/json"), *headers], "client": ("test", 1), "server": ("test", 80)},
                  receive, send)

    asyncio.run(exchange())
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    return status, b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body").decode()


def test_run_endpoints_for_frontend(monkeypatch):
    monkeypatch.setattr(runs, "registry", runs.RunRegistry(browser_factory=lambda: FakeBrowser(_github_pages())))
    status, body = _request("POST", "/api/sourcing/runs", {"query": "Python 工程師", "max_candidates": 1, "sites": ["github"]})
    created = json.loads(body)
    assert status == 201 and created["events_url"].endswith("/events")
    _wait(runs.registry.get(created["run_id"]))
    status, body = _request("GET", created["events_url"])
    assert status == 200 and body.startswith("retry: 3000") and "id: 1\nevent: plan" in body and "event: end" in body
    status, body = _request("GET", created["events_url"], headers=[(b"last-event-id", b"2")])
    assert "id: 1\n" not in body and "id: 3\n" in body
    status, body = _request("GET", created["snapshot_url"])
    assert status == 200 and json.loads(body)["status"] == "done"
    assert _request("GET", "/api/sourcing/runs/nope")[0] == 404
    status, body = _request("POST", "/api/sourcing/runs", {"query": "找 30 歲以下的設計師"})
    assert status == 201 and json.loads(body)["status"] == "rejected"


# ------------------------------------------------------------------ PR #24 回饋
import sys
from types import ModuleType

from sourcing import extract as extract_mod
from sourcing.browser import cleanup_stale_chrome, element_geometry


def _so_pages():
    url = SITES["stackoverflow"].search_url(SearchTerms(("python",), "Taichung"))
    return {url: {"title": "top", "links": [("https://stackoverflow.com/users/1/uk-dev", "UK Dev"),
                                             ("https://stackoverflow.com/users/2/tc-dev", "TC Dev")]}}


def test_unsafe_urls_never_reach_the_frontend(monkeypatch):
    monkeypatch.setattr(apis, "stackoverflow_user", lambda uid: {
        "display_name": "x", "reputation": 10, "location": "Taichung", "link": "",
        "website_url": "javascript:alert(document.cookie)", "top_tags": ["python"]})
    cand = extract_mod.from_stackoverflow_api(SITES["stackoverflow"], "https://stackoverflow.com/users/1/x",
                                              planner.rule_plan("Python 工程師"))
    data = cand.as_dict()
    assert data["personal_site"] is None and all(e["url"].startswith("https://") for e in data["evidence"])
    cand.evidence.append({"label": "壞連結", "url": "data:text/html,<script>"})
    assert "data:" not in json.dumps(cand.as_dict())


def test_stackoverflow_uses_api_only_and_filters_location(monkeypatch):
    users = {"1": ("UK Dev", "Cambridge, United Kingdom"), "2": ("TC Dev", "台中市"), "3": ("TP Dev", "Taipei, Taiwan")}
    calls = []
    monkeypatch.setattr(apis, "stackoverflow_top_answerers", lambda tag: [(i, users[i][0]) for i in users])

    def batch(ids):
        calls.append(list(ids))
        return {i: {"display_name": users[i][0], "reputation": 100, "location": users[i][1],
                    "link": f"https://stackoverflow.com/users/{i}/u{i}", "website_url": ""} for i in ids}

    monkeypatch.setattr(apis, "stackoverflow_users", batch)
    monkeypatch.setattr(apis, "stackoverflow_top_tags", lambda uid: ["python", "django"])
    prep = service.prepare("找會 Python 的工程師，在台中", max_candidates=2, site_ids=["stackoverflow"])
    events = list(service.stream(prep, browser_factory=lambda: pytest.fail("Stack Overflow 不應開瀏覽器")))
    cands = {e["candidate"]["name"]: e["candidate"] for e in events if e["type"] == "candidate"}
    assert calls == [["1", "2", "3"]]  # 一次批次查完
    assert set(cands) == {"TC Dev", "TP Dev"}
    assert cands["TC Dev"]["area"] == "primary" and cands["TC Dev"]["area_label"] == "台中"
    assert cands["TP Dev"]["area"] == "taiwan" and cands["TP Dev"]["location_note"] == "在台灣其他地區（Taipei, Taiwan）"
    assert any(e["type"] == "notice" and "Stack Overflow" in e["message"] for e in events)


def test_one_failing_site_does_not_end_the_run():
    class FlakyBrowser(FakeBrowser):
        def open(self, url):
            if "huggingface.co" in url:
                raise TimeoutError("WebSocketTimeoutException")
            super().open(url)

    pages = {SITES["kaggle"].search_url(SearchTerms(("machine learning",), None)): {
        "title": "k", "links": [("https://www.kaggle.com/alice", "Alice")]},
        "https://www.kaggle.com/alice": {"title": "Alice | Kaggle", "text": ["ML notebooks"], "links": []}}
    prep = service.prepare("找機器學習工程師", max_candidates=2, site_ids=["huggingface", "kaggle"])
    events = list(service.stream(prep, browser_factory=lambda: FlakyBrowser(pages)))
    errors = [e for e in events if e["type"] == "site_error" and e["site"] == "huggingface"]
    assert errors and "TimeoutError" in errors[0]["reason"]
    assert events[-1]["type"] == "done" and any(e["type"] == "candidate" for e in events)


def test_github_name_matches_between_step_and_card():
    plan = planner.rule_plan("Python 工程師")
    cand = extract_mod.summarize(SITES["github"], "https://github.com/hoochanlon", "hoochanlon · GitHub",
                                 ["Working from home"], [], plan, fallback_name="123456")
    assert cand.name == "123456 (@hoochanlon)"
    orcid = extract_mod.summarize(SITES["orcid"], "https://orcid.org/0000-0002-1694-233X", "Lin Chen (0000-0002-1694-233X) - ORCID",
                                  ["Machine learning"], [], plan, fallback_name="0000-0002-1694-233X")
    assert orcid.name == "Lin Chen"


def test_click_geometry_is_in_frame_coordinates():
    page = SimpleNamespace(vw=1440, vh=900)
    element = SimpleNamespace(x=720, y=450, w=200, h=40)
    geo = element_geometry(element, page)
    assert geo["frame"] == {"w": 1280, "h": 800} and geo["click"] == {"x": 640, "y": 400}
    assert geo["box"] == {"x": 551, "y": 382, "w": 178, "h": 36}
    assert element_geometry(SimpleNamespace(x=1), page) is None


def test_steps_and_candidates_carry_geometry_for_the_frontend():
    class GeoBrowser(FakeBrowser):
        def click_link(self, href):
            self.last_click = {"frame": {"w": 1280, "h": 800}, "click": {"x": 100, "y": 200},
                               "box": {"x": 90, "y": 190, "w": 20, "h": 20}}
            return super().click_link(href)

        def card_box(self, href):
            return {"frame": {"w": 1280, "h": 800}, "box": {"x": 50, "y": 150, "w": 600, "h": 90}}

        def name_box(self, *names):
            return {"frame": {"w": 1280, "h": 800}, "box": {"x": 20, "y": 300, "w": 300, "h": 30}}

    prep = service.prepare("Python 工程師", max_candidates=1, site_ids=["github"])
    events = list(service.stream(prep, browser_factory=lambda: GeoBrowser(_github_pages())))
    opened = next(e for e in events if e["type"] == "step" and e["action"] == "open_profile")
    assert opened["geometry"]["click"] == {"x": 100, "y": 200} and opened["geometry"]["box"]["w"] == 600
    cand = next(e for e in events if e["type"] == "candidate")
    assert cand["geometry"]["box"]["y"] == 300


def test_cleanup_kills_only_leftover_agent_chrome(monkeypatch, tmp_path):
    killed = []

    class Proc:
        def __init__(self, pid, cmdline, parents=(), name="chrome.exe"):
            self.pid, self.info, self._parents = pid, {"pid": pid, "name": name, "cmdline": cmdline}, parents

        def parents(self):
            return [SimpleNamespace(pid=p) for p in self._parents]

        def kill(self):
            killed.append(self.pid)

    agent = ["chrome.exe", "--remote-debugging-port=9222", "--user-data-dir=C:/Temp/tscu-chrome-abc"]
    procs = [Proc(1, agent), Proc(2, agent, parents=(os.getpid(),)),
             Proc(3, ["chrome.exe", "--user-data-dir=C:/Users/me/Chrome"]),
             Proc(4, ["python", "-c", "'--remote-debugging-port tscu-chrome-'"], name="python.exe")]
    fake = ModuleType("psutil")
    fake.process_iter = lambda attrs: iter(procs)
    fake.NoSuchProcess = fake.AccessDenied = RuntimeError
    monkeypatch.setitem(sys.modules, "psutil", fake)
    monkeypatch.setattr("sourcing.browser.tempfile.gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr("sourcing.browser.time.sleep", lambda s: None)
    (tmp_path / "tscu-chrome-old").mkdir()
    assert cleanup_stale_chrome() == 1 and killed == [1]
    assert not (tmp_path / "tscu-chrome-old").exists()



def test_orcid_uses_official_api_with_city_institutions(monkeypatch):
    seen = {}

    def fake_orcid(path, params=None, timeout=20.0):
        if path == "expanded-search/":
            seen.setdefault("q", params["q"])  # 第一次是台中的機構；不夠時第二次擴大到台灣
            return {"expanded-result": [{"orcid-id": "0000-0001-2345-6789", "given-names": "Lin", "family-names": "Chen",
                                         "institution-name": ["Feng Chia University"]}]}
        return {"keywords": {"keyword": [{"content": "machine learning; computer vision"}]},
                "researcher-urls": {"researcher-url": [{"url": {"value": "javascript:alert(1)"}},
                                                        {"url": {"value": "https://lin.example.org"}}]},
                "biography": {"content": "Works on ML."}}

    monkeypatch.setattr(apis, "_orcid", fake_orcid)
    monkeypatch.setattr(apis, "openalex_city_institutions", lambda city, **k: [("I1", "Feng Chia University")])
    prep = service.prepare("找台中的機器學習研究員", site_ids=["orcid"])
    events = list(service.stream(prep, browser_factory=lambda: pytest.fail("ORCID 不應開瀏覽器")))
    cand = next(e["candidate"] for e in events if e["type"] == "candidate")
    assert 'affiliation-org-name:("Feng Chia University")' in seen["q"] and '"machine learning"' in seen["q"]
    assert cand["name"] == "Lin Chen" and cand["profile_url"] == "https://orcid.org/0000-0001-2345-6789"
    assert cand["skills"][:2] == ["machine learning", "computer vision"] and cand["fit"] == "部分符合"
    assert cand["personal_site"] == "https://lin.example.org" and "javascript" not in json.dumps(cand)



def test_api_sources_skip_candidates_judged_not_fitting(monkeypatch):
    people = [{"orcid": f"0000-0001-0000-000{i}", "name": f"R{i}", "institutions": ["Feng Chia University"],
               "keywords": ["machine learning"], "biography": "", "urls": []} for i in range(4)]
    monkeypatch.setattr(apis, "orcid_researchers", lambda topics, location, limit: people[:limit])
    verdicts = iter([("不符合", "醫院行政"), ("符合", "ML"), ("不符合", "化學"), ("符合", "CV")])
    monkeypatch.setattr(extract_mod, "judge_fit", lambda *a, **k: next(verdicts))
    prep = service.prepare("找台中的機器學習研究員", max_candidates=2, site_ids=["orcid"])
    events = list(service.stream(prep, browser_factory=lambda: pytest.fail("不應開瀏覽器")))
    kept = [e["candidate"]["name"] for e in events if e["type"] == "candidate"]
    skipped = [e["name"] for e in events if e["type"] == "candidate_skipped"]
    assert kept == ["R1", "R3"] and skipped == ["R0", "R2"]


# ------------------------------------------------------------------ 一頁不夠就換頁
def _people(prefix, n, site="github"):
    base = {"github": "https://github.com/", "kaggle": "https://www.kaggle.com/"}[site]
    return [(f"{base}{prefix}{i}", f"{prefix}{i}") for i in range(n)]


def _profiles(links):
    return {href: {"title": name, "text": [f"{name} writes Python"], "links": []} for href, name in links}


def test_github_moves_to_next_page_until_quota():
    first = SITES["github"].search_url(SearchTerms(("python",), None))
    page1, page2 = _people("a", 3), _people("b", 3)
    pages = {first: {"title": "p1", "links": page1},
             SITES["github"].page_url(first, 2): {"title": "p2", "links": page2},
             **_profiles(page1 + page2)}
    prep = service.prepare("Python 工程師", max_candidates=5, site_ids=["github"])
    events = list(service.stream(prep, browser_factory=lambda: FakeBrowser(pages)))
    names = [e["candidate"]["name"] for e in events if e["type"] == "candidate"]
    assert len(names) == 5 and len(set(names)) == 5
    assert any(e["type"] == "step" and e["action"] == "next_page" and "第 2 頁" in e["detail"] for e in events)


def test_infinite_scroll_sites_scroll_for_more_and_stop_when_exhausted():
    first = SITES["kaggle"].search_url(SearchTerms(("data science",), None))
    batch1, batch2 = _people("k", 2, "kaggle"), _people("m", 2, "kaggle")

    class ScrollBrowser(FakeBrowser):
        scrolls = 0

        def scroll_more(self):
            self.scrolls += 1
            if self.scrolls == 1:  # 第一次捲動載入下一批，之後就沒有了
                self.pages[first]["links"] = batch1 + batch2

    pages = {first: {"title": "k", "links": list(batch1)}, **_profiles(batch1 + batch2)}
    browser = ScrollBrowser(pages)
    prep = service.prepare("找資料科學家", max_candidates=10, site_ids=["kaggle"])
    events = list(service.stream(prep, browser_factory=lambda: browser))
    assert len([e for e in events if e["type"] == "candidate"]) == 4
    assert browser.scrolls == 2 and events[-1]["type"] == "done"


def test_bot_check_on_profile_stops_the_whole_site():
    first = SITES["github"].search_url(SearchTerms(("python",), None))
    links = _people("a", 3)
    pages = {first: {"title": "p1", "links": links}, **_profiles(links)}
    browser = FakeBrowser(pages, challenge_on=["https://github.com/a0"])
    prep = service.prepare("Python 工程師", max_candidates=3, site_ids=["github"])
    events = list(service.stream(prep, browser_factory=lambda: browser))
    assert any(e["type"] == "site_error" and "機器人驗證" in e["reason"] for e in events)
    assert not any(u.endswith("/a1") for u in browser.opened) and not any(e["type"] == "candidate" for e in events)


class HostBrowser(FakeBrowser):
    """搜尋結果頁依網站回傳候選人，不管搜尋字是什麼。"""

    def __init__(self, people):
        pages = {}
        for url, name in people:
            pages[url] = {"title": name, "text": [f"{name} machine learning"], "links": []}
        super().__init__(pages)
        self.people = people

    def result_cards(self):
        if "search" not in self.current:
            return []
        host = self.current.split("/")[2]
        return [(u, n, f"{n} card") for u, n in self.people if u.split("/")[2] == host]


def _location_run(github_people):
    people = [(f"https://github.com/gh{i}", f"gh{i}") for i in range(github_people)] + [
        ("https://huggingface.co/hf1", "hf1"), ("https://www.kaggle.com/kg1", "kg1")]
    browser = HostBrowser(people)
    prep = service.prepare("找機器學習工程師 在台中", max_candidates=3, site_ids=["github", "huggingface", "kaggle"])
    return list(service.stream(prep, browser_factory=lambda: browser)), browser


def test_location_sites_get_the_quota_first():
    events, browser = _location_run(github_people=3)
    cands = [e["candidate"] for e in events if e["type"] == "candidate"]
    assert [c["site"] for c in cands] == ["github"] * 3 and all(c["location_note"] == "" for c in cands)
    assert not any("huggingface" in u or "kaggle" in u for u in browser.opened)
    assert not any(e["type"] == "notice" and "補足" in e["message"] for e in events)


def test_sites_without_location_only_fill_the_gap_and_are_flagged():
    events, _ = _location_run(github_people=1)
    cands = [e["candidate"] for e in events if e["type"] == "candidate"]
    assert [c["site"] for c in cands] == ["github", "huggingface", "kaggle"]
    assert cands[0]["area"] == "primary" and cands[0]["area_label"] == "台中"
    assert all(c["area"] == "unknown" and c["area_label"] == "無法確認是否在台灣" for c in cands[1:])
    notices = [e["message"] for e in events if e["type"] == "notice" and "補足" in e["message"]]
    assert len(notices) == 1 and "Hugging Face、Kaggle" in notices[0]
    assert any(e["type"] == "notice" and "擴大到台灣其他地區" in e["message"] for e in events)
    assert {s["id"]: s["location_filter"] for s in catalog()}["github"] is True


def test_infinite_scroll_skips_seen_cards_before_the_card_limit(monkeypatch):
    """往下捲動的網站保留舊卡片：第一批滿 40 張都不符合，捲動後追加的人仍要看得到。"""
    first = [(f"https://www.kaggle.com/old{i}", f"old{i}") for i in range(service.MAX_CARDS)]
    added = [("https://www.kaggle.com/new1", "new1"), ("https://www.kaggle.com/new2", "new2")]

    class ScrollBrowser(HostBrowser):
        scrolls = 0

        def scroll_more(self):
            self.scrolls += 1
            self.people = first + added

    browser = ScrollBrowser(first + added)
    browser.people = list(first)
    monkeypatch.setattr(service, "summarize", lambda site, url, *a, **k: Candidate(
        site.id, url, url.rsplit("/", 1)[-1], fit="不符合" if "/old" in url else "符合"))
    prep = service.prepare("找機器學習工程師", max_candidates=1, site_ids=["kaggle"])
    events = list(service.stream(prep, browser_factory=lambda: browser))
    assert browser.scrolls == 1
    assert [e["candidate"]["name"] for e in events if e["type"] == "candidate"] == ["new1"]


def test_other_city_api_candidates_wait_for_city_sources(monkeypatch):
    """Stack Overflow 同國家其他城市的人不能先占名額：GitHub 找到台中的人優先。"""
    monkeypatch.setattr(apis, "stackoverflow_top_answerers", lambda tag: [("3", "TP Dev")])
    monkeypatch.setattr(apis, "stackoverflow_users", lambda ids: {"3": {
        "display_name": "TP Dev", "reputation": 100, "location": "Taipei, Taiwan",
        "link": "https://stackoverflow.com/users/3/tp", "website_url": ""}})
    monkeypatch.setattr(apis, "stackoverflow_top_tags", lambda uid: ["python"])
    browser = HostBrowser([("https://github.com/tcdev", "tcdev")])
    prep = service.prepare("找台中 Python 工程師", max_candidates=1, site_ids=["github", "stackoverflow"])
    events = list(service.stream(prep, browser_factory=lambda: browser))
    assert [e["candidate"]["name"] for e in events if e["type"] == "candidate"] == ["tcdev"]
    assert events[-1]["type"] == "done" and events[-1]["count"] == 1

    browser = HostBrowser([])  # GitHub 沒找到人：才補其他城市的人，並標為部分符合
    events = list(service.stream(service.prepare("找台中 Python 工程師", max_candidates=1,
                                                 site_ids=["github", "stackoverflow"]),
                                 browser_factory=lambda: browser))
    cands = [e["candidate"] for e in events if e["type"] == "candidate"]
    assert [c["name"] for c in cands] == ["TP Dev"] and cands[0]["area_label"] == "台灣其他地區"


def test_github_search_keeps_rule_terms_when_model_gives_nothing(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"language": None, "keyword": None})
    text, source, _ = decider.search_text(SITES["github"], planner.rule_plan("找Python工程師"))
    assert text == "type:user language:python location:Taichung" and source == "rules"
    empty = planner.Plan("找人", ["software"], SearchTerms((), None), True, "rules", [])
    assert decider.search_text(SITES["github"], empty)[0] == "type:user developer"


def test_profile_location_decides_area_on_sites_without_location_search():
    """不能依地點搜尋的網站：讀個人頁的所在地，台中照列、台灣以外略過、看不出來的排最後。"""
    people = [("https://www.kaggle.com/far", "far"), ("https://www.kaggle.com/anon", "anon"),
              ("https://www.kaggle.com/tc", "tc"), ("https://www.kaggle.com/tp", "tp")]
    browser = HostBrowser(people)
    browser.pages["https://www.kaggle.com/far"]["text"] = ["far", "Berlin, Germany", "machine learning"]
    browser.pages["https://www.kaggle.com/tc"]["text"] = ["tc", "Taichung, Taiwan", "machine learning"]
    browser.pages["https://www.kaggle.com/tp"]["text"] = ["tp", "台北市", "machine learning"]
    prep = service.prepare("找機器學習工程師", max_candidates=3, site_ids=["kaggle"])
    events = list(service.stream(prep, browser_factory=lambda: browser))
    cands = [(e["candidate"]["name"], e["candidate"]["area"]) for e in events if e["type"] == "candidate"]
    assert cands == [("tc", "primary"), ("tp", "taiwan"), ("anon", "unknown")]  # 看不出地點的排最後
    skipped = [e for e in events if e["type"] == "candidate_skipped"]
    assert skipped[0]["name"] == "far" and "不在台灣" in skipped[0]["reason"]
    assert any(e["type"] == "step" and e["action"] == "hold" for e in events)
    assert not any(e["type"] == "notice" and "擴大到台灣其他地區" in e["message"] for e in events)  # 根本沒有依地點搜尋過


def test_outside_taiwan_is_rejected_and_no_location_defaults_to_taichung():
    prep = service.prepare("找東京的 Python 工程師")
    assert prep.final_event["type"] == "out_of_area" and "東京" in prep.final_event["reason"]
    events = list(service.stream(prep, browser_factory=lambda: pytest.fail("不應開瀏覽器")))
    assert [e["type"] for e in events] == ["out_of_area"]
    plan = planner.rule_plan("找 Python 工程師").as_dict()
    assert plan["location"] == "Taichung" and plan["search_area"] == {
        "primary": "Taichung", "primary_label": "台中", "fallback": "Taiwan", "default": True}
    assert planner.rule_plan("中國醫藥大學的 AI 研究員").outside_taiwan == ""  # 台灣的學校，不是國外
    assert planner.rule_plan("後端工程師 大雅區").terms.location == "Taichung"
    assert planner.rule_plan("Python engineer in New Taipei").terms.location == "New Taipei"
    assert planner.rule_plan("找台灣的 Python 工程師").as_dict()["search_area"]["fallback"] is None


def test_llm_location_must_be_in_taiwan(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    answer = {"categories": ["software"], "skills": ["python"], "location": "outside_taiwan", "has_public_work": True}
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: answer)
    assert planner.plan("找矽谷附近的 Python 工程師").outside_taiwan
    assert planner.plan("找台中或國外的 Python 工程師").outside_taiwan == ""  # 有寫台灣的地點就照台灣找
    answer["location"] = "Paris"  # 清單外的值不採用
    assert planner.plan("找 Python 工程師").terms.location == "Taichung"


def test_github_ladder_keeps_skills_and_lets_the_area_widen(monkeypatch):
    from sourcing.sites import github_ladder
    assert github_ladder("Taichung", "rust", "backend") == [
        "language:rust backend location:Taichung", "backend location:Taichung", "language:rust location:Taichung"]
    assert github_ladder("Taichung", None, None) == ["location:Taichung"]  # 完全沒有技能時才只用地點
    counts = {"language:rust location:Taichung": 3}
    monkeypatch.setattr(apis, "github_user_count", lambda q: counts.get(q, 1))
    plan = planner.rule_plan("找 Rust 工程師 在台中")
    text, _, note = decider.search_text(SITES["github"], plan, need=10)
    assert text == "type:user language:rust location:Taichung" and "人數最多" in note
