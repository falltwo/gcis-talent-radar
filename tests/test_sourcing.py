"""找人 agent：網站目錄、需求規劃、擷取、流程與 SSE API。瀏覽器一律用假的，不連網。"""
import asyncio
import json

import pytest

from api.main import app
from sourcing import extract, llm, planner, service
from sourcing.extract import Link
from sourcing.sites import SITES, SearchTerms, blocked_reason, catalog, sites_for


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
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
    page = [Link("https://github.com/alice/radar", "radar"), Link("https://github.com/alice/followers"),
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
class FakeBrowser:
    """模擬搜尋結果頁與個人頁；記錄開過的網址。"""

    def __init__(self, pages, *, challenge_on=()):
        self.pages = pages
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

    def screenshot(self):
        return "data:image/jpeg;base64,AAAA"

    def challenge(self):
        return "驗證頁" if any(self.current.startswith(p) for p in self.challenge_on) else None

    def jev_steps(self, goal, domains, **kw):
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
    monkeypatch.setattr(service, "SourcingBrowser", lambda: browser)
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
    session.evaluate = lambda expr: session.href
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
    accept = SimpleNamespace(index=3, href="", in_view=True, covered=False)
    b = _jev_browser([_decision("click", 3), _decision("done", satisfied=0.9)], [accept])
    steps = list(b.jev_steps("close banner", ("orcid.org",)))
    assert [s["action"] for s in steps] == ["click", "done"]
    assert b._act.calls == [("click", 3)]


def test_jev_cannot_type_or_leave_allowed_domain(monkeypatch):
    monkeypatch.setattr("sourcing.browser.time.sleep", lambda s: None)
    outside = SimpleNamespace(index=1, href="https://evil.example/login", in_view=True, covered=False)
    b = _jev_browser([_decision("click", 1)], [outside])
    steps = list(b.jev_steps("x", ("orcid.org",)))
    assert steps[0]["action"] == "none" and b._act.calls == []
    b = _jev_browser([_decision("type_text", 1)], [outside])
    assert list(b.jev_steps("x", ("orcid.org",)))[0]["action"] == "none"


def test_jev_low_confidence_stops_and_missing_key_skips():
    b = _jev_browser([_decision("press_escape", confidence=0.2), _decision("done")], [])
    steps = list(b.jev_steps("x", ("orcid.org",)))
    assert len(steps) == 1 and steps[0]["action"] == "press_escape"
    b._client = None
    assert list(b.jev_steps("x", ("orcid.org",))) == []


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
    prep = service.prepare("找機器學習研究員", site_ids=["openalex", "orcid"])
    browser = FakeBrowser({})
    events = list(service.stream(prep, browser_factory=lambda: browser))
    assert any(e["type"] == "site_error" and e["site"] == "openalex" for e in events)
    assert any("orcid.org" in u for u in browser.opened)


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
