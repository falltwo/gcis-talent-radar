"""Immutable report payloads, resolution snapshots and audit in one SQLite store."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from engine.report_scenario import ReportError, canonical_json, digest

DDL = """
CREATE TABLE IF NOT EXISTS comparison_resolutions (
 token TEXT PRIMARY KEY, scenario_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
 payload_hash TEXT NOT NULL, expires_at REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comparison_reports (
 report_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS report_idempotency (
 idempotency_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
 report_id TEXT NOT NULL REFERENCES comparison_reports(report_id)
);
CREATE TABLE IF NOT EXISTS report_events (
 event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, report_id TEXT,
 outcome TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_events_request ON report_events(request_id);
CREATE INDEX IF NOT EXISTS idx_report_events_report ON report_events(report_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReportStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        conn = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(DDL)
            yield conn
        except ReportError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise ReportError("REPORT_STORAGE_UNAVAILABLE", "報告保存或必要稽核失敗，請稍後重試。", 503) from exc
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _decode(row) -> dict:
        if not row:
            raise ReportError("REPORT_NOT_FOUND", "找不到這份報告。", 404)
        try:
            data = json.loads(row["payload_json"])
            if digest(data) != row["payload_hash"]:
                raise ValueError("payload hash mismatch")
            return data
        except (ValueError, TypeError) as exc:
            raise ReportError("REPORT_INTEGRITY_FAILED", "報告內容完整性檢查失敗，不顯示此版本。", 503) from exc

    def save_resolution(self, token: str, scenario_hash: str, payload: dict, expires_at: float):
        with self.connection() as conn, conn:
            conn.execute("INSERT INTO comparison_resolutions VALUES (?, ?, ?, ?, ?, ?)",
                         (token, scenario_hash, canonical_json(payload), digest(payload), expires_at, utc_now()))

    def resolution(self, token: str, scenario_hash: str) -> dict:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM comparison_resolutions WHERE token=?", (token,)).fetchone()
        if not row or row["expires_at"] <= time.time():
            raise ReportError("RESOLUTION_EXPIRED", "資料期別確認已過期，請重新解析並確認。", 409)
        if row["scenario_hash"] != scenario_hash:
            raise ReportError("SCENARIO_CHANGED", "條件已改變，請重新解析並確認資料期別。", 409)
        return self._decode(row)

    def idempotent_report(self, key: str, request_hash: str):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM report_idempotency WHERE idempotency_key=?", (key,)).fetchone()
            if not row:
                return None
            if row["request_hash"] != request_hash:
                raise ReportError("IDEMPOTENCY_CONFLICT", "此建立請求已用於不同條件，請重新解析後建立。", 409)
            report_row = conn.execute("SELECT * FROM comparison_reports WHERE report_id=?", (row["report_id"],)).fetchone()
        return self._decode(report_row)

    def create_report(self, report: dict, key: str, request_hash: str) -> dict:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                prior = conn.execute("SELECT * FROM report_idempotency WHERE idempotency_key=?", (key,)).fetchone()
                if prior:
                    if prior["request_hash"] != request_hash:
                        raise ReportError("IDEMPOTENCY_CONFLICT", "建立請求與先前條件不符。", 409)
                    row = conn.execute("SELECT * FROM comparison_reports WHERE report_id=?", (prior["report_id"],)).fetchone()
                    conn.rollback()
                    return self._decode(row)
                conn.execute("INSERT INTO comparison_reports VALUES (?, ?, ?, ?)",
                             (report["report_id"], canonical_json(report), digest(report), report["created_at"]))
                conn.execute("INSERT INTO report_idempotency VALUES (?, ?, ?)", (key, request_hash, report["report_id"]))
                self._event(conn, report["request_id"], report["report_id"], "REPORT_COMMITTED", {
                    "manifest_hash": report["manifest"]["manifest_hash"],
                    "payload_hash": digest(report), "data_status": report["data_status"],
                })
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return report

    def get_report(self, report_id: str) -> dict:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM comparison_reports WHERE report_id=?", (report_id,)).fetchone()
        return self._decode(row)

    @staticmethod
    def _event(conn, request_id: str, report_id: str, outcome: str, payload: dict):
        conn.execute("INSERT INTO report_events VALUES (?, ?, ?, ?, ?, ?)",
                     (str(uuid.uuid4()), request_id, report_id, outcome, canonical_json(payload), utc_now()))

    def save_answer_event(self, report_id: str, answer: dict, question_hash: str, char_count: int):
        with self.connection() as conn, conn:
            self._event(conn, answer["request_id"], report_id, "ANSWER_COMMITTED", {
                "question_hash": question_hash, "question_char_count": char_count,
                "ai_status": answer.get("ai_status"), "catalog_hash": answer.get("catalog_hash"),
                "render_digest": answer.get("render_digest"), "events": answer.get("events", []),
            })
