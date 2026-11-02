-- Additive migration: recruitment tables do not modify official-data tables.
CREATE TABLE IF NOT EXISTS recruitment_requests (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('DRAFT','APPROVED','CLOSED')),
    data TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS recruitment_requests_tenant ON recruitment_requests(tenant_id);
CREATE TABLE IF NOT EXISTS recruitment_jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    request_id TEXT NOT NULL REFERENCES recruitment_requests(id),
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('OPEN','CLOSED')),
    created_at TEXT NOT NULL,
    UNIQUE(tenant_id, platform, external_id)
);
CREATE TABLE IF NOT EXISTS recruitment_candidates (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    data TEXT NOT NULL,
    rights_basis TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    do_not_contact INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(tenant_id, source, external_ref)
);
CREATE TABLE IF NOT EXISTS recruitment_applications (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    request_id TEXT NOT NULL REFERENCES recruitment_requests(id),
    candidate_id TEXT NOT NULL REFERENCES recruitment_candidates(id) ON DELETE CASCADE,
    origin TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('NEW','MATCHED','INVITED','INTERESTED','DECLINED','NO_RESPONSE','INTERVIEW','OFFERED','HIRED','REJECTED','WITHDRAWN')),
    match_result TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(request_id, candidate_id)
);
CREATE TABLE IF NOT EXISTS recruitment_invitations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    application_id TEXT NOT NULL UNIQUE REFERENCES recruitment_applications(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('PENDING_APPROVAL','APPROVED','SENT','FAILED','CANCELLED','INTERESTED','DECLINED','NO_RESPONSE')),
    message TEXT NOT NULL,
    approved_by TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    delivery_reference TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recruitment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS recruitment_applications_tenant ON recruitment_applications(tenant_id, request_id);
CREATE INDEX IF NOT EXISTS recruitment_candidates_expiry ON recruitment_candidates(tenant_id, expires_at);
CREATE INDEX IF NOT EXISTS recruitment_events_tenant ON recruitment_events(tenant_id, id);
