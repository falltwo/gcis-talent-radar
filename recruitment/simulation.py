"""104 demo state machine. Intentionally contains no HTTP client or platform SDK."""
import json

from recruitment.auth import require_hr
from recruitment.workflow import fail, now, uid


STATUS_LABELS = {
    "PENDING_APPROVAL": "模擬刊登：待核准",
    "PROCESSING": "模擬刊登：處理中",
    "SUCCEEDED": "模擬刊登：成功",
    "FAILED": "模擬刊登：失敗",
    "CANCELLED": "模擬刊登：已取消",
}


def present(row):
    record = dict(row)
    record["snapshot"] = json.loads(record["snapshot"])
    return {**record, "platform": "104", "mode": "SIMULATION", "is_simulated": True,
            "status_label": STATUS_LABELS[record["status"]], "sent_to_platform": False,
            "notice": "僅為104刊登流程模擬，未送至104，未建立真實職缺。"}


class SimulationWorkflow:
    """Mixin using the service's authenticated transactions and audit events."""

    def create_simulation(self, principal, request_id, model):
        with self.connection() as conn:
            req = self.open_request(conn, request_id, principal)
            existing = conn.execute(
                "SELECT * FROM recruitment_simulated_publications WHERE tenant_id=? AND request_id=? AND idempotency_key=?",
                (principal.tenant_id, request_id, model.idempotency_key),
            ).fetchone()
            if existing:
                if existing["initial_scenario"] != model.scenario:
                    fail("The idempotency key was already used with a different scenario")
                return present(existing)
            # A new key must not accidentally produce parallel/successful demo jobs.
            if conn.execute("SELECT 1 FROM recruitment_simulated_publications WHERE request_id=? AND status!='CANCELLED'", (request_id,)).fetchone():
                fail("A simulation already exists; use its retry endpoint after failure")
            identifier, ts = uid(), now()
            conn.execute(
                "INSERT INTO recruitment_simulated_publications VALUES(?,?,?,?,?,?,?,?,'PENDING_APPROVAL',NULL,0,NULL,NULL,?,?)",
                (identifier, principal.tenant_id, request_id, req["revision"], req["data"], model.idempotency_key, model.scenario, model.scenario, ts, ts),
            )
            self.event(conn, principal, identifier, "SIMULATION_104_CREATED")
            return present(self.get(conn, "simulated_publications", identifier, principal))

    def simulation(self, principal, identifier):
        with self.connection() as conn:
            return present(self.get(conn, "simulated_publications", identifier, principal))

    def approve_simulation(self, principal, identifier):
        require_hr(principal)
        with self.connection() as conn:
            row = self.get(conn, "simulated_publications", identifier, principal)
            req = self.open_request(conn, row["request_id"], principal)
            if req["revision"] != row["request_revision"]:
                fail("Simulation requirements changed; create a new reviewed snapshot")
            if row["status"] == "PROCESSING":
                return present(row)
            if row["status"] != "PENDING_APPROVAL":
                fail("Only pending simulations can be approved")
            conn.execute("UPDATE recruitment_simulated_publications SET status='PROCESSING',approved_by=?,attempts=attempts+1,updated_at=? WHERE id=?",
                         (principal.actor_id, now(), identifier))
            self.event(conn, principal, identifier, "SIMULATION_104_PROCESSING")
            return present(self.get(conn, "simulated_publications", identifier, principal))

    def complete_simulation(self, principal, identifier):
        require_hr(principal)
        with self.connection() as conn:
            row = self.get(conn, "simulated_publications", identifier, principal)
            self.open_request(conn, row["request_id"], principal)
            if row["status"] in {"SUCCEEDED", "FAILED"}:
                return present(row)
            if row["status"] != "PROCESSING":
                fail("Approve the simulation before completing it")
            success = row["scenario"] == "SUCCESS"
            status = "SUCCEEDED" if success else "FAILED"
            conn.execute("UPDATE recruitment_simulated_publications SET status=?,simulated_job_id=?,error_code=?,updated_at=? WHERE id=?",
                         (status, "sim104-" + identifier if success else None,
                          None if success else "SIMULATED_PLATFORM_FAILURE", now(), identifier))
            self.event(conn, principal, identifier, "SIMULATION_104_" + status)
            return present(self.get(conn, "simulated_publications", identifier, principal))

    def retry_simulation(self, principal, identifier, model):
        require_hr(principal)
        with self.connection() as conn:
            row = self.get(conn, "simulated_publications", identifier, principal)
            self.open_request(conn, row["request_id"], principal)
            if row["status"] != "FAILED" or row["attempts"] >= 3:
                fail("Only failed simulations below three attempts can be retried")
            conn.execute("UPDATE recruitment_simulated_publications SET status='PENDING_APPROVAL',scenario=?,approved_by=NULL,error_code=NULL,updated_at=? WHERE id=?",
                         (model.scenario, now(), identifier))
            self.event(conn, principal, identifier, "SIMULATION_104_RETRY_REQUESTED")
            return present(self.get(conn, "simulated_publications", identifier, principal))

    def list_simulations(self, principal, limit, offset, request_id=None):
        with self.connection() as conn:
            where, params = "tenant_id=?", [principal.tenant_id]
            if request_id:
                self.get(conn, "requests", request_id, principal)
                where += " AND request_id=?"
                params.append(request_id)
            rows = conn.execute(f"SELECT * FROM recruitment_simulated_publications WHERE {where} ORDER BY created_at,id LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
            return {"mode": "SIMULATION", "is_simulated": True, "sent_to_platform": False,
                    "notice": "僅為104刊登流程模擬，未送至104。", "items": [present(row) for row in rows], "limit": limit, "offset": offset}
