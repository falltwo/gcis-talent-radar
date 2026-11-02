"""Atomic workflow transitions, tenant isolation, and deterministic matching."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from agent.prompt_guard import PROTECTED_TRAITS
from recruitment.auth import require_hr
from recruitment.drafting import prepare_requirement


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid4())


def fail(message):
    raise HTTPException(409, message)


class RecruitmentService:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        with self.connection() as conn:
            conn.executescript((Path(__file__).resolve().parents[1] / "database" / "recruitment.sql").read_text(encoding="utf-8"))

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            # Serialize checks and writes, so two workers cannot both dispatch/approve.
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(409, "Duplicate record or conflicting workflow operation") from None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get(self, conn, table, identifier, principal):
        # table names are internal constants, never supplied by API callers.
        row = conn.execute(f"SELECT * FROM recruitment_{table} WHERE id=? AND tenant_id=?", (identifier, principal.tenant_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Record not found")
        return dict(row)

    def event(self, conn, principal, identifier, action):
        conn.execute("INSERT INTO recruitment_events(tenant_id,actor_id,entity_id,action,created_at) VALUES(?,?,?,?,?)",
                     (principal.tenant_id, principal.actor_id, identifier, action, now()))

    @staticmethod
    def decoded(row):
        row = dict(row)
        for key in ("data", "match_result"):
            if row.get(key) is not None:
                row[key] = json.loads(row[key])
        return row

    def requirement(self, principal, model, identifier=None):
        data = model.model_dump()
        criteria = " ".join([data["title"], data["district"], data["shift"], *data["required_skills"], *data["trainable_skills"]])
        if any(pattern.search(criteria) for pattern in PROTECTED_TRAITS.values()):
            raise HTTPException(422, "Use job-related criteria only; protected-trait criteria are not supported")
        with self.connection() as conn:
            ts = now()
            if identifier:
                row = self.get(conn, "requests", identifier, principal)
                if row["status"] != "DRAFT":
                    fail("Only draft requirements can be edited; create a new request for revised approved criteria")
                conn.execute("UPDATE recruitment_requests SET data=?, revision=revision+1, updated_at=? WHERE id=?",
                             (json.dumps(data, ensure_ascii=False), ts, identifier))
            else:
                identifier = uid()
                conn.execute("INSERT INTO recruitment_requests VALUES(?,?,1,'DRAFT',?,NULL,NULL,?,?)",
                             (identifier, principal.tenant_id, json.dumps(data, ensure_ascii=False), ts, ts))
            self.event(conn, principal, identifier, "REQUIREMENT_SAVED")
            return self.decoded(self.get(conn, "requests", identifier, principal))

    def prepare(self, principal, model):
        result = prepare_requirement(model.needs)
        with self.connection() as conn:
            self.event(conn, principal, uid(), "REQUIREMENT_PREPARED_UNVERIFIED")
        return result

    def approve(self, principal, identifier, expected_revision):
        require_hr(principal)
        with self.connection() as conn:
            row = self.get(conn, "requests", identifier, principal)
            if row["status"] != "DRAFT":
                fail("Only draft requirements can be approved")
            if row["revision"] != expected_revision:
                fail("Requirement changed since review; reload the current revision before approval")
            ts = now()
            conn.execute("UPDATE recruitment_requests SET status='APPROVED',approved_by=?,approved_at=?,updated_at=? WHERE id=?",
                         (principal.actor_id, ts, ts, identifier))
            self.event(conn, principal, identifier, "REQUIREMENT_APPROVED")
            return self.decoded(self.get(conn, "requests", identifier, principal))

    def open_request(self, conn, identifier, principal):
        row = self.get(conn, "requests", identifier, principal)
        if row["status"] != "APPROVED":
            fail("An approved, open recruitment request is required")
        return row

    def publish(self, principal, identifier, model):
        require_hr(principal)
        with self.connection() as conn:
            self.open_request(conn, identifier, principal)
            existing = conn.execute("SELECT * FROM recruitment_jobs WHERE tenant_id=? AND platform=? AND external_id=?",
                                    (principal.tenant_id, model.platform, model.external_id)).fetchone()
            if existing:
                if existing["request_id"] != identifier:
                    fail("This external job is already associated with another request")
                return dict(existing)
            job_id = uid()
            conn.execute("INSERT INTO recruitment_jobs VALUES(?,?,?,?,?,'OPEN',?)",
                         (job_id, principal.tenant_id, identifier, model.platform, model.external_id, now()))
            self.event(conn, principal, job_id, "MANUAL_PUBLICATION_RECORDED")
            return self.get(conn, "jobs", job_id, principal)

    def import_candidate(self, principal, identifier, model):
        with self.connection() as conn:
            self.open_request(conn, identifier, principal)
            existing = conn.execute("SELECT * FROM recruitment_candidates WHERE tenant_id=? AND source=? AND external_ref=?",
                                    (principal.tenant_id, model.source, model.external_ref)).fetchone()
            if existing:
                if existing["expires_at"] <= now():
                    fail("Existing candidate has expired; HR must purge expired data before re-import")
                candidate_id = existing["id"]
                # Do not silently overwrite evidence already used by approved invitations.
                if json.loads(existing["data"]) != self.candidate_data(model):
                    fail("Candidate already exists with different evidence; review before changing it")
            else:
                candidate_id = uid()
                conn.execute("INSERT INTO recruitment_candidates VALUES(?,?,?,?,?,?,?,0,?)",
                             (candidate_id, principal.tenant_id, model.source, model.external_ref,
                              json.dumps(self.candidate_data(model), ensure_ascii=False), model.rights_basis,
                              model.expires_at.isoformat(), now()))
                self.event(conn, principal, candidate_id, "AUTHORIZED_CANDIDATE_IMPORTED")
            existing_app = conn.execute("SELECT * FROM recruitment_applications WHERE request_id=? AND candidate_id=?", (identifier, candidate_id)).fetchone()
            if existing_app:
                return self.decoded(existing_app)
            app_id, ts = uid(), now()
            conn.execute("INSERT INTO recruitment_applications VALUES(?,?,?,?,?,'NEW',NULL,?,?)",
                         (app_id, principal.tenant_id, identifier, candidate_id, model.origin, ts, ts))
            self.event(conn, principal, app_id, "APPLICATION_CREATED")
            return self.decoded(self.get(conn, "applications", app_id, principal))

    @staticmethod
    def candidate_data(model):
        return model.model_dump(include={"display_name", "skills", "available_shifts", "districts", "experience_months"})

    def correct_candidate(self, principal, identifier, model):
        require_hr(principal)
        with self.connection() as conn:
            row = self.get(conn, "candidates", identifier, principal)
            if row["expires_at"] <= now() or row["do_not_contact"]:
                fail("Candidate has expired or opted out")
            if conn.execute("SELECT 1 FROM recruitment_applications WHERE candidate_id=? AND stage NOT IN ('NEW','MATCHED')", (identifier,)).fetchone():
                fail("Evidence is frozen after invitation or a final decision")
            if conn.execute("SELECT 1 FROM recruitment_invitations i JOIN recruitment_applications a ON a.id=i.application_id WHERE a.candidate_id=?", (identifier,)).fetchone():
                fail("Evidence is frozen after an invitation is drafted")
            conn.execute("UPDATE recruitment_candidates SET data=? WHERE id=?", (json.dumps(model.model_dump(), ensure_ascii=False), identifier))
            conn.execute("UPDATE recruitment_applications SET stage='NEW',match_result=NULL,updated_at=? WHERE candidate_id=?", (now(), identifier))
            self.event(conn, principal, identifier, "CANDIDATE_EVIDENCE_CORRECTED")
            return self.decoded(self.get(conn, "candidates", identifier, principal))

    def active_application(self, conn, identifier, principal):
        app = self.get(conn, "applications", identifier, principal)
        req = self.open_request(conn, app["request_id"], principal)
        candidate = self.get(conn, "candidates", app["candidate_id"], principal)
        if candidate["expires_at"] <= now() or candidate["do_not_contact"]:
            fail("Candidate has expired or opted out")
        if app["stage"] in {"DECLINED", "NO_RESPONSE", "REJECTED", "WITHDRAWN", "HIRED"}:
            fail("Application is closed")
        return app, req, candidate

    def match(self, principal, identifier):
        with self.connection() as conn:
            app, req, candidate = self.active_application(conn, identifier, principal)
            if app["stage"] not in {"NEW", "MATCHED"}:
                fail("Matching is only allowed before an invitation is created")
            if conn.execute("SELECT 1 FROM recruitment_invitations WHERE application_id=?", (identifier,)).fetchone():
                fail("Invitation already exists; matching evidence is frozen")
            r, c = json.loads(req["data"]), json.loads(candidate["data"])
            checks = []
            def add(name, actual, expected, passed):
                checks.append({"criterion": name, "expected": expected, "observed": actual,
                               "result": "UNKNOWN" if actual is None else ("PASS" if passed else "FAIL")})
            for skill in r["required_skills"]:
                add("skill", c["skills"], skill, c["skills"] is not None and skill in c["skills"])
            add("district", c["districts"], r["district"], c["districts"] is not None and r["district"].casefold() in c["districts"])
            add("shift", c["available_shifts"], r["shift"], c["available_shifts"] is not None and r["shift"].casefold() in c["available_shifts"])
            if r["min_experience_months"]:
                add("experience_months", c["experience_months"], r["min_experience_months"],
                    c["experience_months"] is not None and c["experience_months"] >= r["min_experience_months"])
            results = {x["result"] for x in checks}
            result = {"decision": "NOT_MATCHED" if "FAIL" in results else ("NEEDS_REVIEW" if "UNKNOWN" in results else "MATCHED"),
                      "checks": checks, "request_revision": req["revision"], "method": "exact_job_criteria_v1",
                      "limitations": "Structured imported evidence only; no inference of missing skills, no hiring probability."}
            conn.execute("UPDATE recruitment_applications SET match_result=?,stage='MATCHED',updated_at=? WHERE id=?",
                         (json.dumps(result, ensure_ascii=False), now(), identifier))
            self.event(conn, principal, identifier, "MATCH_COMPLETED")
            return result

    def draft_invitation(self, principal, identifier, model):
        with self.connection() as conn:
            app, _, _ = self.active_application(conn, identifier, principal)
            if app["stage"] != "MATCHED" or not app["match_result"]:
                fail("Match the candidate before drafting an invitation")
            if json.loads(app["match_result"])["decision"] == "NOT_MATCHED":
                fail("Candidate does not meet required criteria")
            invitation_id, ts = uid(), now()
            conn.execute("INSERT INTO recruitment_invitations VALUES(?,?,?,'PENDING_APPROVAL',?,NULL,0,NULL,?,?)",
                         (invitation_id, principal.tenant_id, identifier, model.message, ts, ts))
            self.event(conn, principal, invitation_id, "INVITATION_DRAFTED")
            return self.get(conn, "invitations", invitation_id, principal)

    def approve_invitation(self, principal, identifier, reviewed_unknowns=False):
        require_hr(principal)
        with self.connection() as conn:
            row = self.get(conn, "invitations", identifier, principal)
            application, _, _ = self.active_application(conn, row["application_id"], principal)
            if row["status"] != "PENDING_APPROVAL":
                fail("Invitation is not awaiting HR approval")
            if json.loads(application["match_result"])["decision"] == "NEEDS_REVIEW" and not reviewed_unknowns:
                fail("HR must explicitly acknowledge unknown matching criteria or correct evidence before drafting")
            conn.execute("UPDATE recruitment_invitations SET status='APPROVED',approved_by=?,updated_at=? WHERE id=?",
                         (principal.actor_id, now(), identifier))
            self.event(conn, principal, identifier, "INVITATION_APPROVED_WITH_UNKNOWNS" if reviewed_unknowns else "INVITATION_APPROVED")
            return self.get(conn, "invitations", identifier, principal)

    def delivery(self, principal, identifier, model):
        require_hr(principal)
        with self.connection() as conn:
            row = self.get(conn, "invitations", identifier, principal)
            self.active_application(conn, row["application_id"], principal)
            if row["status"] == model.outcome and row["delivery_reference"] == model.reference:
                return row  # Safe client retry: no duplicate attempt/event.
            if row["status"] != "APPROVED":
                fail("Only an approved invitation can have a manual delivery recorded")
            ts = now()
            conn.execute("UPDATE recruitment_invitations SET status=?,attempts=attempts+1,delivery_reference=?,updated_at=? WHERE id=?",
                         (model.outcome, model.reference, ts, identifier))
            if model.outcome == "SENT":
                conn.execute("UPDATE recruitment_applications SET stage='INVITED',updated_at=? WHERE id=?", (ts, row["application_id"]))
            self.event(conn, principal, identifier, "MANUAL_DELIVERY_" + model.outcome)
            return self.get(conn, "invitations", identifier, principal)

    def retry(self, principal, identifier):
        require_hr(principal)
        with self.connection() as conn:
            row = self.get(conn, "invitations", identifier, principal)
            self.active_application(conn, row["application_id"], principal)
            if row["status"] != "FAILED" or row["attempts"] >= 3:
                fail("Only failed deliveries below three attempts can be retried")
            conn.execute("UPDATE recruitment_invitations SET status='APPROVED',updated_at=? WHERE id=?", (now(), identifier))
            self.event(conn, principal, identifier, "MANUAL_RETRY_APPROVED")
            return self.get(conn, "invitations", identifier, principal)

    def reply(self, principal, identifier, model):
        with self.connection() as conn:
            row = self.get(conn, "invitations", identifier, principal)
            self.active_application(conn, row["application_id"], principal)
            if row["status"] != "SENT":
                fail("Only sent invitations can receive a response")
            ts = now()
            conn.execute("UPDATE recruitment_invitations SET status=?,updated_at=? WHERE id=?", (model.outcome, ts, identifier))
            conn.execute("UPDATE recruitment_applications SET stage=?,updated_at=? WHERE id=?", (model.outcome, ts, row["application_id"]))
            self.event(conn, principal, identifier, "MANUAL_REPLY_" + model.outcome)
            return self.get(conn, "invitations", identifier, principal)

    def stage(self, principal, identifier, model):
        require_hr(principal)
        with self.connection() as conn:
            app, _, _ = self.active_application(conn, identifier, principal)
            allowed = {"INTERVIEW": {"INTERESTED"}, "OFFERED": {"INTERVIEW"}, "HIRED": {"OFFERED"},
                       "REJECTED": {"NEW", "MATCHED", "INVITED", "INTERESTED", "INTERVIEW", "OFFERED"},
                       "WITHDRAWN": {"NEW", "MATCHED", "INVITED", "INTERESTED", "INTERVIEW", "OFFERED"}}
            if app["stage"] not in allowed[model.stage]:
                fail("Invalid application stage transition")
            conn.execute("UPDATE recruitment_applications SET stage=?,updated_at=? WHERE id=?", (model.stage, now(), identifier))
            if model.stage in {"WITHDRAWN", "REJECTED"}:
                self.cancel(conn, "application_id", identifier)
            self.event(conn, principal, identifier, "APPLICATION_" + model.stage)
            return self.decoded(self.get(conn, "applications", identifier, principal))

    @staticmethod
    def cancel(conn, field, identifier):
        conn.execute(f"UPDATE recruitment_invitations SET status='CANCELLED',updated_at=? WHERE {field}=? AND status IN ('PENDING_APPROVAL','APPROVED','FAILED','SENT')", (now(), identifier))

    def close(self, principal, identifier):
        require_hr(principal)
        with self.connection() as conn:
            self.get(conn, "requests", identifier, principal)
            ts = now()
            conn.execute("UPDATE recruitment_requests SET status='CLOSED',updated_at=? WHERE id=?", (ts, identifier))
            conn.execute("UPDATE recruitment_jobs SET status='CLOSED' WHERE request_id=?", (identifier,))
            for row in conn.execute("SELECT id FROM recruitment_applications WHERE request_id=?", (identifier,)).fetchall():
                self.cancel(conn, "application_id", row["id"])
            self.event(conn, principal, identifier, "REQUEST_CLOSED")
            return self.decoded(self.get(conn, "requests", identifier, principal))

    def opt_out(self, principal, identifier):
        require_hr(principal)
        with self.connection() as conn:
            self.get(conn, "candidates", identifier, principal)
            conn.execute("UPDATE recruitment_candidates SET do_not_contact=1 WHERE id=?", (identifier,))
            for row in conn.execute("SELECT id FROM recruitment_applications WHERE candidate_id=?", (identifier,)).fetchall():
                self.cancel(conn, "application_id", row["id"])
            self.event(conn, principal, identifier, "CANDIDATE_OPTED_OUT")
            return {"candidate_id": identifier, "do_not_contact": True}

    def delete_candidate(self, principal, identifier):
        require_hr(principal)
        with self.connection() as conn:
            self.get(conn, "candidates", identifier, principal)
            conn.execute("DELETE FROM recruitment_candidates WHERE id=?", (identifier,))
            self.event(conn, principal, identifier, "CANDIDATE_DELETED")
            return {"deleted": True}

    def purge(self, principal):
        require_hr(principal)
        with self.connection() as conn:
            rows = conn.execute("SELECT id FROM recruitment_candidates WHERE tenant_id=? AND expires_at<=?", (principal.tenant_id, now())).fetchall()
            for row in rows:
                conn.execute("DELETE FROM recruitment_candidates WHERE id=?", (row["id"],))
                self.event(conn, principal, row["id"], "EXPIRED_CANDIDATE_DELETED")
            return {"deleted": len(rows)}

    def listing(self, principal, table, limit, offset, request_id=None):
        with self.connection() as conn:
            where, params = "tenant_id=?", [principal.tenant_id]
            # Do not surface expired candidate evidence or related messages.
            if table == "applications":
                where += " AND candidate_id IN (SELECT id FROM recruitment_candidates WHERE expires_at>?)"
                params.append(now())
            elif table == "invitations":
                where += " AND application_id IN (SELECT a.id FROM recruitment_applications a JOIN recruitment_candidates c ON c.id=a.candidate_id WHERE c.expires_at>?)"
                params.append(now())
            if request_id:
                self.get(conn, "requests", request_id, principal)
                if table == "invitations":
                    where += " AND application_id IN (SELECT id FROM recruitment_applications WHERE request_id=?)"
                else:
                    where += " AND request_id=?"
                params.append(request_id)
            rows = conn.execute(f"SELECT * FROM recruitment_{table} WHERE {where} ORDER BY " + ("id" if table == "events" else "created_at,id") + " LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
            return {"items": [self.decoded(r) for r in rows], "limit": limit, "offset": offset}

    def candidate(self, principal, identifier):
        with self.connection() as conn:
            row = self.get(conn, "candidates", identifier, principal)
            if row["expires_at"] <= now():
                raise HTTPException(410, "Candidate retention has expired")
            return self.decoded(row)

    def dashboard(self, principal):
        with self.connection() as conn:
            result = {}
            for table, field in (("requests", "status"), ("applications", "stage"), ("invitations", "status")):
                rows = conn.execute(f"SELECT {field},COUNT(*) AS count FROM recruitment_{table} WHERE tenant_id=? GROUP BY {field}", (principal.tenant_id,)).fetchall()
                result[table] = {r[field]: r["count"] for r in rows}
            return result
