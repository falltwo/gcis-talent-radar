"""End-to-end report/service/API tests against isolated official-shaped inputs."""
import csv
import hashlib
import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.comparison_report import ComparisonReportService
from engine.report_scenario import (
    CLASSIFICATION_VERSION, RETRIEVAL_VERSION, ReportError, index_month,
    make_hiring_plan, month_index, validate_scenario,
)


def scenario():
    return {
        "schema_version": "1.0", "districts": ["大雅區", "潭子區", "神岡區"],
        "manufacturing": {"division_code": "29", "classification_version": CLASSIFICATION_VERSION},
        "occupation": {"type": "KEYWORD", "keyword": "CNC", "retrieval_profile_version": RETRIEVAL_VERSION},
        "observation": {"mode": "LATEST_AVAILABLE", "month": None, "window_months": 3, "knowledge_cutoff": None},
        "hiring_plan": {"net_hires": 31, "start_month": "2026-11", "end_month": "2027-01"},
    }


def gcis_context(s, **kwargs):
    end = min(s["observation"]["month"] or "2026-08", "2026-08")
    end_index = month_index(end)
    city = {"available": True, "start": index_month(end_index-11), "end": end,
            "baseline_start": index_month(end_index-23), "baseline_end": index_month(end_index-12),
            "current_sum": 240, "baseline_sum": 120, "change_pct": 100,
            "monthly_rows": [{"year_month": index_month(i), "new_company_count": 10 if i < end_index-11 else 20}
                             for i in range(end_index-23, end_index+1)],
            "evidence": {"source_url": "https://data.gcis.nat.gov.tw/main/index", "source_name": "GCIS fixture", "data_period": end}}
    return {"available": True, "city": city, "local": [{"district": d, "industry_code": s["manufacturing"]["division_code"],
             "start": index_month(end_index-s["observation"]["window_months"]+1), "end": end, "available": True,
             "new_company_count": index+1, "capital_increase_company_count": None, "dissolved_company_count": None,
             "qualification": "PARTIAL", "reason_codes": ["CURRENT_LABEL_RETROSPECTIVE"],
             "evidence": {"source_url": "https://data.gcis.nat.gov.tw/main/index", "data_period": end}}
            for index, d in enumerate(s["districts"])], "findings": [], "next_actions": [],
            "source_manifest": [{"dataset_id": "gcis-fixture", "artifact_hash": "a"*64}], "cutoff_month": end}


@pytest.fixture
def service(tmp_path):
    source = tmp_path / "source.sqlite3"
    conn = sqlite3.connect(source)
    conn.executescript((Path(__file__).resolve().parents[1] / "database/schema.sql").read_text(encoding="utf-8"))
    for rid, district, openings in [("a1", "大雅區", 3), ("a2", "大雅區", 2), ("b1", "潭子區", 7)]:
        conn.execute("""INSERT INTO official_job_vacancies(snapshot_date,record_id,district,postal_code,
         occupation_title,openings,work_location,company_name,source_dataset_id,fetched_at)
         VALUES (?,?,?,?,?,?,?,?,?,?)""", ("2026-10-05",rid,district,"428","CNC機械操作",openings,district,"同一公司","44062","2026-10-05T10:00:00+08:00"))
    for district, count in [("大雅區",2),("潭子區",1),("神岡區",0)]:
        conn.execute("INSERT INTO official_job_fetch_audit VALUES (?,?,?,?,?,?,?,?,?)",
                     ("2026-10-05",district,"428",count,count,0,1000,0,"2026-10-05T10:00:00+08:00"))
    conn.execute("""INSERT INTO labor_insurance_baseline VALUES
      ('11412','66','臺中市','1','產業勞工','C','製造業','1','參加就保',20056,361509,36201.78,'100999','https://data.gov.tw/dataset/100999','2026-10-05')""")
    conn.commit(); conn.close()
    processed = tmp_path / "processed"; processed.mkdir()
    with (processed / "tc_factory_count_district_monthly.csv").open("w",encoding="utf-8",newline="") as handle:
        writer=csv.writer(handle); writer.writerow(["year_month","district","industry","factories"])
        writer.writerows([("2026-07",d,"機械設備製造業",n) for d,n in [("大雅區",8),("潭子區",3),("神岡區",0)]])
    return ComparisonReportService(source_db_path=source, store_path=tmp_path/"reports.sqlite3",
                                   processed_dir=processed, raw_dir=tmp_path/"raw", gcis_capture=gcis_context)


def build(service, s=None, key=None):
    s = s or scenario(); resolution = service.resolve(s)
    return service.build({"scenario":s,"resolution_token":resolution["resolution_token"]}, key or "test-"+resolution["resolution_token"])


@pytest.mark.parametrize("mutate", [
    lambda s:s.update(extra=True),
    lambda s:s.update(districts=["大雅區","大雅區"]),
    lambda s:s["hiring_plan"].update(net_hires=True),
    lambda s:s["hiring_plan"].update(start_month="2026-13"),
    lambda s:s["hiring_plan"].update(end_month="2026-10"),
    lambda s:s["hiring_plan"].update(end_month="2028-01"),
    lambda s:s["observation"].update(month="2026-10"),
    lambda s:s["occupation"].update(keyword=" "),
])
def test_strict_input_rejects_invalid_scenarios(mutate):
    s=scenario(); mutate(s)
    with pytest.raises(ReportError): validate_scenario(s)


def test_planning_and_official_values_are_separate(service):
    a=build(service); s=scenario(); s["hiring_plan"]["net_hires"]=60; b=build(service,s)
    assert [r["people"] for r in a["planning"]["monthly_targets"]]==[11,10,10]
    assert [r["people"] for r in b["planning"]["monthly_targets"]]==[20,20,20]
    assert a["jobs"]==b["jobs"]
    assert [r["requested_workers"] for r in a["jobs"]["comparisons"]]==[5,7,0]


def test_readonly_source_and_saved_report(service):
    before=hashlib.sha256(service.source_db_path.read_bytes()).hexdigest()
    report=build(service)
    assert service.get(report["report_id"])==report
    assert hashlib.sha256(service.source_db_path.read_bytes()).hexdigest()==before
    assert report["content"]["summary_blocks"]
    assert report["manifest"]["resolved_periods"]["jobs"]=="2026-10-05"


def test_snapshot_freezes_confirmation_and_old_report(service):
    s=scenario(); resolved=service.resolve(s)
    conn=sqlite3.connect(service.source_db_path)
    conn.execute("UPDATE official_job_vacancies SET openings=100 WHERE record_id='a1'");conn.commit();conn.close()
    report=service.build({"scenario":s,"resolution_token":resolved["resolution_token"]},"freeze-test")
    assert report["jobs"]["comparisons"][0]["requested_workers"]==5
    assert build(service)["jobs"]["comparisons"][0]["requested_workers"]==102
    assert service.get(report["report_id"])==report


def test_expired_resolution_and_scenario_changes_rejected(service):
    s=scenario(); r=service.resolve(s)
    changed=deepcopy(s); changed["occupation"]["keyword"]="品管"
    with pytest.raises(ReportError,match="條件已改變"):
        service.build({"scenario":changed,"resolution_token":r["resolution_token"]},"changed-scenario")
    with service.store.connection() as conn,conn:
        conn.execute("UPDATE comparison_resolutions SET expires_at=0")
    with pytest.raises(ReportError,match="過期"):
        service.build({"scenario":s,"resolution_token":r["resolution_token"]},"expired-resolution")


def test_idempotency_retry_survives_resolution_expiry(service):
    s=scenario(); r=service.resolve(s); body={"scenario":s,"resolution_token":r["resolution_token"]}
    a=service.build(body,"same-request")
    with service.store.connection() as conn,conn:conn.execute("UPDATE comparison_resolutions SET expires_at=0")
    assert service.build(body,"same-request")==a
    changed=deepcopy(body);changed["scenario"]["hiring_plan"]["net_hires"]=60
    with pytest.raises(ReportError) as exc: service.build(changed,"same-request")
    assert exc.value.status==409


def test_history_never_borrows_later_job_snapshot(service):
    s=scenario();s["observation"].update(mode="FIXED_MONTH",month="2026-07")
    report=build(service,s)
    assert not report["jobs"]["available"]
    assert not any(f["metric_id"].startswith("jobs.") for f in report["content"]["facts"])
    assert report["background"]["wage"]["period"]=="2025-12"
    assert report["data_status"]=="LIMITED"


def test_query_cap_disables_rankings_without_suppressing_lower_bound(service):
    conn=sqlite3.connect(service.source_db_path)
    conn.execute("UPDATE official_job_fetch_audit SET query_limit=2,limit_reached=1 WHERE district='大雅區'");conn.commit();conn.close()
    report=build(service)
    groups=[g for g in report["content"]["metric_groups"] if g["metric_id"].startswith("jobs.")]
    assert all(g["comparison_status"]!="COMPARABLE_SAMPLE" for g in groups)
    assert any("至少" in b["text"] for b in report["content"]["summary_blocks"])
    assert not any(c["type"]=="COMPARISON" and c["rule_id"].startswith("JOB") for c in report["content"]["claims"])


def test_missing_audit_is_unknown_not_zero(service):
    conn=sqlite3.connect(service.source_db_path);conn.execute("DELETE FROM official_job_fetch_audit WHERE district='潭子區'");conn.commit();conn.close()
    report=build(service)
    assert report["jobs"]["available"] is False
    assert report["jobs"]["comparisons"]==[]


def test_valid_question_and_audit_do_not_mutate_report(service):
    report=build(service)
    def provider(request):
        first=request["catalog"][0]
        return {"report_id":request["report_id"],"catalog_hash":request["catalog_hash"],"sections":[{"heading_id":first["heading_id"],"claim_ids":[first["claim_id"]]}]}
    result=service.question(report["report_id"],{"question":"解釋職缺比較"},provider=provider)
    assert result["ai_status"]=="VERIFIED"
    assert service.get(report["report_id"])==report
    with service.store.connection() as conn:
        event=json.loads(conn.execute("SELECT payload_json FROM report_events WHERE request_id=?",(result["request_id"],)).fetchone()[0])
    assert "question_hash" in event and "question" not in event


def test_unsafe_model_text_never_displayed(service):
    report=build(service);calls=[]
    def provider(request):
        calls.append(1)
        return {"report_id":request["report_id"],"catalog_hash":request["catalog_hash"],"text":"人才非常充足，放心擴廠"}
    result=service.question(report["report_id"],{"question":"說明本報告"},provider=provider)
    assert result["ai_status"]=="FALLBACK" and len(calls)==2
    assert "放心擴廠" not in result["answer"]


def test_no_model_key_keeps_report_and_exports_usable(service):
    report=build(service)
    with patch.dict("os.environ",{"OPENROUTER_API_KEY":""}):
        answer=service.question(report["report_id"],{"question":"解釋這份比較"})
    assert answer["ai_status"]=="FALLBACK" and answer["blocks"]
    exported=service.export_html(report["report_id"])
    assert report["report_id"] in exported and "未知" in exported and "來源" in exported


def test_print_uses_scope_labels_periods_and_readable_units(service):
    report=build(service)
    exported=service.export_html(report["report_id"])
    assert "各來源的固定觀察" in exported
    assert "2026-10-05" in exported and "2026-07" in exported
    assert "僅描述；不作區域排名" in exported
    assert "[EXACT_WITHIN_SCOPE]" not in exported and " posting" not in exported


def test_report_retains_source_ids_not_unused_vacancy_text(service):
    report=build(service)
    row=report["jobs"]["comparisons"][0]
    assert "top_vacancies" not in row
    assert row["source_vacancy_refs"][0]["record_id"]
    assert "company_name" not in row["source_vacancy_refs"][0]
    locator=row["evidence"]["row_locator"]
    assert locator["district"]=="大雅區" and locator["source_snapshot_hash"]


def test_future_source_snapshot_is_not_observed_data(service):
    conn=sqlite3.connect(service.source_db_path)
    for table in ("official_job_vacancies","official_job_fetch_audit"):
        conn.execute(f"UPDATE {table} SET snapshot_date='2999-01-01'")
    conn.commit();conn.close()
    report=build(service)
    assert not report["jobs"]["available"]
    assert report["manifest"]["resolved_periods"]["jobs"] is None


def test_old_render_contract_keeps_saved_view_but_refuses_new_model_render(service,monkeypatch):
    import engine.report_renderer as renderer
    report=build(service)
    monkeypatch.setattr(renderer,"current_render_contract_hash",lambda:"f"*64)
    def provider(request):raise AssertionError("model must not be called")
    with pytest.raises(ReportError) as exc:
        service.question(report["report_id"],{"question":"請解釋比較"},provider=provider)
    assert exc.value.code=="RENDER_CONTRACT_INCOMPATIBLE" and exc.value.status==409
    assert service.get(report["report_id"])==report
    assert report["report_id"] in service.export_html(report["report_id"])


def test_storage_hash_tampering_fails_closed(service):
    report=build(service)
    with service.store.connection() as conn,conn:
        conn.execute("UPDATE comparison_reports SET payload_json='{}' WHERE report_id=?",(report["report_id"],))
    with pytest.raises(ReportError) as exc:service.get(report["report_id"])
    assert exc.value.code=="REPORT_INTEGRITY_FAILED"


def test_report_and_build_audit_are_one_transaction(service,monkeypatch):
    s=scenario();r=service.resolve(s)
    def fail(*args,**kwargs):raise sqlite3.OperationalError("audit unavailable")
    monkeypatch.setattr(service.store,"_event",fail)
    with pytest.raises(ReportError):service.build({"scenario":s,"resolution_token":r["resolution_token"]},"audit-failure")
    with service.store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM comparison_reports").fetchone()[0]==0
        assert conn.execute("SELECT COUNT(*) FROM report_idempotency").fetchone()[0]==0


async def asgi_request(app,path,method="GET",body=None,headers=None):
    sent=[]; delivered=False
    data=json.dumps(body,ensure_ascii=False).encode("utf-8") if body is not None else b""
    async def receive():
        nonlocal delivered
        if delivered:raise AssertionError("Unexpected request-body read after the complete request")
        delivered=True
        return {"type":"http.request","body":data,"more_body":False}
    async def send(message):sent.append(message)
    await app({"type":"http","asgi":{"version":"3.0","spec_version":"2.4"},"http_version":"1.1","method":method,"scheme":"http","path":path,"raw_path":path.encode(),"query_string":b"","root_path":"","headers":[(b"content-type",b"application/json"),*((k.lower().encode(),v.encode()) for k,v in (headers or {}).items())],"server":("testserver",80),"client":("127.0.0.1",1)},receive,send)
    start=next(item for item in sent if item["type"]=="http.response.start")
    payload=b"".join(item.get("body",b"") for item in sent if item["type"]=="http.response.body")
    return start["status"],payload


def test_complete_api_routes_and_validation(service,monkeypatch):
    import api.main as api
    monkeypatch.setattr(api,"comparison_report_service",service)
    def call(path,method="GET",body=None,headers=None):
        async def inline_threadpool(function, /, *args, **kwargs):
            return function(*args, **kwargs)
        # Synchronous SQLite endpoints need no real socketpair. This executes the
        # actual router/body parsing while avoiding Windows sandbox loop sockets.
        with patch("fastapi.routing.run_in_threadpool", inline_threadpool), patch("fastapi.dependencies.utils.run_in_threadpool", inline_threadpool):
            coroutine=asgi_request(api.app,path,method,body,headers)
            try:
                coroutine.send(None)
            except StopIteration as completed:
                status,payload=completed.value
            else:
                raise AssertionError("Synchronous API unexpectedly requested async IO")
            finally:
                coroutine.close()
        return status,json.loads(payload)
    status,options=call("/api/comparison-options");assert status==200 and options["classification_version"]==CLASSIFICATION_VERSION
    status,r=call("/api/reports/expansion-comparison/resolve","POST",scenario());assert status==200
    status,report=call("/api/reports/expansion-comparison","POST",{"scenario":scenario(),"resolution_token":r["resolution_token"]},{"Idempotency-Key":"api-create-test"});assert status==201
    assert call("/api/reports/"+report["report_id"])[1]==report
    status,error=call("/api/reports/expansion-comparison/resolve","POST",{});assert status==422 and error["detail"]["error_code"]=="INVALID_SCENARIO"
    assert call("/api/reports/not-found")[0]==404
