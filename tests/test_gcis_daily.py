"""每日更新經濟部商工資料：每日 API、接續與次數上限、併入清冊、資料庫與 API。不連網，平臺回應用假的。"""
import datetime as dt
import json

import pandas as pd
import pytest

from etl import daily_refresh, scheduler
from etl.sources import gcis_daily, gcis_registry

SETUP, DISSOLVED, CHANGE = (gcis_daily.DAILY[k][0] for k in ("setup", "dissolved", "change"))
BASIC = gcis_daily.BASIC


class FakeResponse:
    def __init__(self, data=None, text=None, status=200):
        self.status_code = status
        self.text = text if text is not None else json.dumps(data, ensure_ascii=False)

    def json(self):
        return json.loads(self.text)


class FakeGcis:
    """假的平臺：每日名單、每家公司的應用一資料；記下每次呼叫。"""

    def __init__(self, lists, companies):
        self.lists, self.companies, self.calls = lists, companies, []

    def get(self, url, params=None, timeout=None):
        oid = url.rsplit("/", 1)[-1]
        flt = params["$filter"]
        self.calls.append((oid, flt))
        if oid == BASIC:
            rec = self.companies.get(flt.rsplit(" ", 1)[-1])
            return FakeResponse([rec] if rec else None, text="" if not rec else None)
        rows = self.lists.get((oid, flt.rsplit(" ", 1)[-1]), [])
        skip, top = int(params["$skip"]), int(params["$top"])
        page = rows[skip:skip + top]
        return FakeResponse(page, text="" if not page else None)


def _company(cid, name, location, capital=1_000_000, paid=0, setup="1140101"):
    return {"Business_Accounting_NO": cid, "Company_Name": name, "Company_Location": location,
            "Capital_Stock_Amount": capital, "Paid_In_Capital_Amount": paid, "Company_Setup_Date": setup}


@pytest.fixture
def lists_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(gcis_daily, "LISTS", tmp_path / "gcis_lists")
    monkeypatch.setattr(gcis_daily, "RAW_DATA_DIR", tmp_path)
    monkeypatch.setattr(gcis_registry, "RAW", tmp_path / "gcis_lists")
    monkeypatch.setattr(gcis_registry, "TAX", tmp_path / "tax_registry")
    return tmp_path / "gcis_lists"


def _client(fake, max_calls=None):
    budget = gcis_daily.Budget(max_calls)
    return gcis_daily.Client(budget, rate_per_sec=1e9, get=fake.get), budget


DAY = dt.date(2026, 11, 3)


def _fake_day():
    lists = {
        (SETUP, "1151103"): [{"Business_Accounting_NO": "11111111"}, {"Business_Accounting_NO": "22222222"}],
        (DISSOLVED, "1151103"): [{"Business_Accounting_NO": "33333333"}],
        (CHANGE, "1151103"): [{"Business_Accounting_NO": "44444444"}, {"Business_Accounting_NO": "55555555"}],
    }
    companies = {
        "11111111": _company("11111111", "台中新設有限公司", "臺中市西屯區市政路1號", capital=500000),
        "22222222": _company("22222222", "台北新設有限公司", "臺北市中正區許昌街17號"),
        "33333333": _company("33333333", "台中解散股份有限公司", "台中市北屯區崇德路1號", capital=9_000_000,
                             paid=3_000_000, setup="1080506"),
        "44444444": _company("44444444", "台中增資股份有限公司", "臺中市大雅區中清路1號", capital=20_000_000,
                             paid=8_000_000),
        "55555555": _company("55555555", "外縣市變更有限公司", "新竹市東區光復路1號"),
    }
    return FakeGcis(lists, companies)


def test_roc_date():
    assert gcis_daily.roc_date(dt.date(2026, 11, 3)) == "1151103"
    assert gcis_daily.roc_date(dt.date(2011, 1, 5)) == "1000105"


def test_fetch_day_keeps_only_taichung_and_only_looks_up_known_taichung_changes():
    fake = _fake_day()
    client, budget = _client(fake)
    out = gcis_daily.fetch_day(client, DAY, roster={"44444444"})
    assert [r["統一編號"] for r in out["setup"]] == ["11111111"]  # 臺北的不要
    assert out["setup"][0]["資本額"] == 500000 and out["setup"][0]["核准設立日期"] == "1151103"
    dissolved = out["dissolved"][0]
    assert dissolved["核准設立日期"] == "1080506" and dissolved["資本額"] == 3_000_000  # 股份有限公司用實收
    assert [r["統一編號"] for r in out["change"]] == ["44444444"]
    looked_up = [f for oid, f in fake.calls if oid == BASIC]
    assert not any("55555555" in f for f in looked_up)  # 不在臺中名冊的變更不查
    assert budget.calls == len(fake.calls)


def test_client_handles_holidays_errors_and_paging():
    rows = [{"Business_Accounting_NO": f"{i:08d}"} for i in range(1003)]
    fake = FakeGcis({(CHANGE, "1151103"): rows}, {})
    client, _ = _client(fake)
    assert len(client.day_list("change", DAY)) == 1003  # 一頁 1000 筆，翻頁
    assert client.day_list("setup", DAY) == []  # 假日：空字串
    blocked = gcis_daily.Client(gcis_daily.Budget(), rate_per_sec=1e9,
                                get=lambda *a, **k: FakeResponse(text="非授權介接之IP(1.2.3.4)，請查明後繼續。"))
    with pytest.raises(gcis_daily.GcisApiError, match="非授權"):
        blocked.day_list("setup", DAY)


def test_fetch_range_writes_files_resumes_and_stops_at_the_budget(lists_dir):
    fake = _fake_day()
    client, budget = _client(fake, max_calls=4)  # 不夠抓完一整天
    result = gcis_daily.fetch_range(DAY, DAY, budget=budget, client=client, today=DAY + dt.timedelta(days=10),
                                    log=lambda m: None)
    assert result["stopped"] and not result["fetched_days"]
    assert not list(lists_dir.glob("*/daily/*.csv"))  # 沒抓完的那天不寫檔

    client, budget = _client(fake)
    result = gcis_daily.fetch_range(DAY, DAY, budget=budget, client=client, today=DAY + dt.timedelta(days=10),
                                    log=lambda m: None)
    assert result["fetched_days"] == ["2026-11-03"] and result["updated_through"] == "2026-11-03"
    setup = pd.read_csv(gcis_daily.daily_path("setup", DAY), dtype=str)
    assert list(setup.columns) == gcis_daily.COLUMNS["setup"] and setup["統一編號"].tolist() == ["11111111"]

    calls = len(fake.calls)
    client, budget = _client(fake)
    result = gcis_daily.fetch_range(DAY, DAY, budget=budget, client=client, today=DAY + dt.timedelta(days=10),
                                    log=lambda m: None)
    assert result["skipped_days"] == 1 and len(fake.calls) == calls  # 已抓過的舊日子不重抓
    client, budget = _client(fake)
    gcis_daily.fetch_range(DAY, DAY, budget=budget, client=client, today=DAY + dt.timedelta(days=1),
                           log=lambda m: None)
    assert len(fake.calls) > calls  # 最近幾天每次重抓（晚進來的資料）


def _write_monthly(lists_dir, kind, month, rows):
    path = lists_dir / kind / f"{month}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["序號"] + gcis_daily.COLUMNS[kind]
    pd.DataFrame([[i] + r for i, r in enumerate(rows, 1)], columns=cols).to_csv(path, index=False, encoding="utf-8-sig")


def test_gap_and_load_lists_prefer_the_monthly_list(lists_dir):
    for kind in gcis_daily.DAILY:
        _write_monthly(lists_dir, kind, "2026-09", [])
    assert gcis_daily.latest_list_month() == "2026-09"
    assert gcis_daily.gap_start(dt.date(2026, 11, 5)) == dt.date(2026, 10, 1)
    assert gcis_daily.updated_through() == "2026-09-30"
    _write_monthly(lists_dir, "setup", "2026-09",
                   [["11111111", "月報公司", "臺中市西屯區市政路1號", "100000", "1150915"]])
    for day, cid in ((dt.date(2026, 9, 15), "99999999"), (dt.date(2026, 10, 2), "77777777")):
        for kind in gcis_daily.DAILY:
            path = gcis_daily.daily_path(kind, day)
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = [[cid, "每日公司", "臺中市南屯區文心路1號", "200000", gcis_daily.roc_date(day)]] if kind == "setup" else []
            pd.DataFrame(rows, columns=gcis_daily.COLUMNS[kind]).to_csv(path, index=False, encoding="utf-8-sig")
    df = gcis_registry.load_lists()
    assert set(df["company_id"]) == {"11111111", "77777777"}  # 9 月已有清冊，9/15 的每日資料不用
    assert df.set_index("company_id").loc["77777777", "source"] == "daily_api"
    assert gcis_daily.updated_through() == "2026-10-02"
    events = gcis_registry.build_events(df)
    assert events.set_index("company_id").loc["77777777", "event_day"] == "2026-10-02"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    from database.db_manager import db
    monkeypatch.setattr(db, "db_path", str(tmp_path / "test.db"))
    return db


def test_events_load_into_the_database_and_api(temp_db, monkeypatch):
    from engine.gcis_company_events import get_company_events

    assert get_company_events()["available"] is False
    events = pd.DataFrame([
        {"event_day": "2026-10-02", "event": "new", "company_id": "77777777", "company_name": "每日公司",
         "district": "南屯區", "industry_code": "26", "industry_source": "tax_registry", "capital": 200000.0,
         "capital_delta": float("nan"), "source": "daily_api"},
        {"event_day": "2026-09-20", "event": "capital_increase", "company_id": "44444444", "company_name": "增資公司",
         "district": "大雅區", "industry_code": "47", "industry_source": "gcis_api_item", "capital": 8e6,
         "capital_delta": 3e6, "source": "monthly_list"},
        {"event_day": "2023-01-01", "event": "new", "company_id": "1", "company_name": "太舊", "district": "中區",
         "industry_code": None, "industry_source": "unclassified", "capital": 1.0, "capital_delta": float("nan"),
         "source": "monthly_list"},
    ])
    result = daily_refresh.load_company_events(events, today=dt.date(2026, 11, 5))
    assert result["rows"] == 2 and result["daily_api_rows"] == 1  # 24 個月以前的不載入
    data = get_company_events(days=60)
    assert data["updated_through"] == "2026-10-02" and data["provisional_from"] == "2026-10-02"
    assert data["totals"] == {"new": 1, "dissolved": 0, "capital_increase": 1}
    assert {r["section"]: r["name"] for r in data["by_industry"]} == {"C": "製造業", "G": "批發及零售業"}
    assert data["events"][0]["company_name"] == "每日公司"
    only = get_company_events(days=60, district="大雅區")
    assert only["totals"]["new"] == 0 and only["totals"]["capital_increase"] == 1

    from fastapi.testclient import TestClient
    from api.main import app
    res = TestClient(app).get("/api/official/company-events", params={"days": 60, "section": "c"})
    assert res.status_code == 200 and res.json()["totals"]["new"] == 1


def test_industry_section():
    assert daily_refresh.industry_section("26") == ("C", "製造業")
    assert daily_refresh.industry_section("62") == ("J", "出版影音及資通訊業")
    assert daily_refresh.industry_section(None) == (None, None)


def test_one_failing_step_does_not_stop_the_refresh(tmp_path, monkeypatch, lists_dir):
    monkeypatch.setattr(daily_refresh, "LOG_PATH", tmp_path / "_daily_refresh.json")
    ran = []

    def boom():
        raise RuntimeError("平臺維護中")

    report = daily_refresh.run(max_calls=10, steps={"a": boom, "b": lambda: ran.append("b") or {"rows": 1}},
                               log=lambda m: None)
    assert ran == ["b"] and report["ok"] is False
    assert report["steps"]["a"]["error"].startswith("RuntimeError") and report["steps"]["b"]["rows"] == 1
    assert json.loads((tmp_path / "_daily_refresh.json").read_text(encoding="utf-8"))["steps"]["b"]["ok"]


def test_scheduler_runs_once_a_day_and_only_when_enabled(tmp_path, monkeypatch):
    now = dt.datetime(2026, 11, 5, 7, 0)
    assert scheduler.due(now, None, 6)
    assert not scheduler.due(now, "2026-11-05T06:10:00+08:00", 6)  # 今天跑過了
    assert scheduler.due(now, "2026-11-04T06:10:00+08:00", 6)  # 昨天跑的、今天 6 點已過
    assert not scheduler.due(dt.datetime(2026, 11, 5, 5, 0), "2026-11-04T06:10:00", 6)  # 還沒到今天的時間
    monkeypatch.setattr(scheduler, "LOCK", tmp_path / ".lock")
    assert scheduler.acquire_lock() and not scheduler.acquire_lock()  # 同時只能一個在跑
    scheduler.release_lock()
    assert scheduler.acquire_lock()
    monkeypatch.delenv("GCIS_DAILY_REFRESH", raising=False)
    assert scheduler.start() is None


def test_command_line_skips_when_another_refresh_is_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scheduler, "LOCK", tmp_path / ".lock")
    monkeypatch.setattr(daily_refresh, "run", lambda **k: pytest.fail("已有人在跑，不應再跑"))
    assert scheduler.acquire_lock()
    with pytest.raises(SystemExit) as exc:
        daily_refresh.main([])
    assert exc.value.code == 0 and "略過" in capsys.readouterr().out


def _write_daily(day, fetched_on=None):
    import os
    for kind in gcis_daily.DAILY:
        path = gcis_daily.daily_path(kind, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([], columns=gcis_daily.COLUMNS[kind]).to_csv(path, index=False, encoding="utf-8-sig")
        if fetched_on:
            ts = dt.datetime.combine(fetched_on, dt.time(12)).timestamp()
            os.utime(path, (ts, ts))


def test_coverage_tells_missing_days_from_zero_and_marks_today_partial(lists_dir):
    for kind in gcis_daily.DAILY:
        _write_monthly(lists_dir, kind, "2026-09", [])
    _write_daily(dt.date(2026, 11, 4), fetched_on=dt.date(2026, 11, 5))  # 隔天抓的：完整
    _write_daily(dt.date(2026, 11, 5), fetched_on=dt.date(2026, 11, 5))  # 當天抓的：未完整
    cov = gcis_daily.coverage(dt.date(2026, 9, 29), dt.date(2026, 11, 5))
    assert cov["2026-09-30"] == "monthly_list" and "2026-10-15" not in cov  # 沒抓的日子不列
    assert cov["2026-11-04"] == "daily_api" and cov["2026-11-05"] == "daily_api_partial"
    assert gcis_daily.updated_through() == "2026-11-04"  # 當天的還不算


def test_daily_api_starts_today_and_then_continues_from_the_last_day(lists_dir, monkeypatch):
    for kind in gcis_daily.DAILY:
        _write_monthly(lists_dir, kind, "2026-09", [])
    seen = {}
    monkeypatch.setattr(gcis_daily, "fetch_range", lambda start, end, **k: seen.update(start=start, end=end) or {})
    today = dt.date(2026, 11, 5)
    daily_refresh._daily_api(gcis_daily.Budget(), today, backfill_days=0)
    assert seen == {"start": today, "end": today}  # 第一次只抓今天，不從 10/1 補起
    _write_daily(today, fetched_on=today)
    later = dt.date(2026, 11, 9)  # 中間電腦關機幾天
    daily_refresh._daily_api(gcis_daily.Budget(), later, backfill_days=0)
    assert seen == {"start": today, "end": later}  # 接著上次那天（當天抓的不完整，重抓）
    daily_refresh._daily_api(gcis_daily.Budget(), today, backfill_days=60)
    assert seen["start"] == dt.date(2026, 10, 1)  # 手動補資料最多補到清冊之後的第一天


def test_api_marks_missing_and_partial_days(temp_db):
    from engine.gcis_company_events import get_company_events

    events = pd.DataFrame([{"event_day": d, "event": "new", "company_id": cid, "company_name": "x", "district": "西屯區",
                            "industry_code": "26", "industry_source": "tax_registry", "capital": 1.0,
                            "capital_delta": float("nan"), "source": "daily_api"}
                           for d, cid in (("2026-11-04", "1"), ("2026-11-05", "2"))])
    daily_refresh.load_company_events(events, today=dt.date(2026, 11, 5))
    conn = temp_db.get_connection()
    conn.executemany("INSERT INTO gcis_event_coverage (day, source) VALUES (?, ?)",
                     [("2026-11-02", "daily_api"), ("2026-11-04", "daily_api"), ("2026-11-05", "daily_api_partial")])
    conn.commit()
    conn.close()
    data = get_company_events(days=4)
    by_day = {d["date"]: d for d in data["daily"]}
    assert data["missing_days"] == ["2026-11-03"] and by_day["2026-11-03"]["new"] is None  # 沒有資料，不是 0
    assert by_day["2026-11-02"]["new"] == 0 and by_day["2026-11-04"]["new"] == 1
    assert data["partial_days"] == ["2026-11-05"] and data["updated_through"] == "2026-11-04"


def test_tax_registry_addresses_with_full_width_spaces_still_find_the_district():
    addresses = pd.Series(["臺中市南\u3000區忠明南路1號", "台中市西\u3000區民權路2號", "臺中市西屯區市政路3號",
                           "南投縣中寮鄉中寮村永平路1號"])
    found = gcis_registry.taichung_district(addresses)
    assert found.tolist()[:3] == ["南區", "西區", "西屯區"]  # 稅籍寫「南　區」，中間有全形空白
    assert pd.isna(found.iloc[3])
