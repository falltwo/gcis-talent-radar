"""Privacy-minimizing JSONL audit trail for governed agent decisions."""
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "reports" / "agent_audit.jsonl"


class AuditLogError(RuntimeError):
    """Raised when a decision cannot be written to the audit trail."""


def write_agent_audit(
    query: str,
    *,
    scope_guard: Dict[str, Any],
    prompt_guard: Dict[str, Any],
    outcome: str,
    model_called: bool,
    policy_guard: Optional[Dict[str, Any]] = None,
    tool_calls: Optional[list] = None,
    verification: Optional[Dict[str, Any]] = None,
) -> str:
    """Append one event; record a query digest, never the raw prompt."""
    normalized_query = (query or "").strip()
    request_id = str(uuid.uuid4())
    event = {
        "schema_version": 3,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "query_sha256": hashlib.sha256(normalized_query.encode("utf-8")).hexdigest(),
        "query_char_count": len(normalized_query),
        "configured_model": os.environ.get("OPENROUTER_MODEL", "openai/gpt-6-luna"),
        "scope_guard": {
            "decision": scope_guard.get("decision"),
            "category": scope_guard.get("category"),
            "implementation": scope_guard.get("implementation"),
            "version": scope_guard.get("version"),
            "rule_score": scope_guard.get("rule_score"),
            "reason": scope_guard.get("reason"),
        },
        "prompt_guard": {
            "decision": prompt_guard.get("decision"),
            "policy_code": prompt_guard.get("policy_code"),
            "matched_traits": prompt_guard.get("matched_traits", []),
            "hiring_context": prompt_guard.get("hiring_context", False),
            "active_hiring_context": prompt_guard.get("active_hiring_context", False),
            "discriminatory_decision_request": prompt_guard.get("discriminatory_decision_request", False),
            "reason": prompt_guard.get("reason"),
        },
        "policy_guard": {
            "called": (policy_guard or {}).get("called", False),
            "status": (policy_guard or {}).get("status", "NOT_CALLED"),
            "decision": (policy_guard or {}).get("decision", "NOT_RUN"),
            "category": (policy_guard or {}).get("category", "none"),
            "latency_ms": (policy_guard or {}).get("latency_ms", 0),
        },
        "outcome": outcome,
        "model_called": model_called,
        "tool_calls": tool_calls or [],
        "verification_status": (verification or {}).get("status", "NOT_RUN"),
    }

    log_path = Path(os.environ.get("AGENT_AUDIT_LOG_PATH", str(DEFAULT_LOG_PATH)))
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as exc:
        raise AuditLogError("無法寫入治理稽核日誌；本次請求已停止。") from exc
    return request_id
