"""SQLite persistence for deals, approval history and convergence state."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.state import NegotiationDealState

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "redliner_deals.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DealRepository:
    """Small, thread-safe-enough SQLite repository.

    A new connection is opened per operation. WAL mode keeps the FastAPI server
    and the Gmail poller from blocking each other on short writes.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        configured = os.environ.get("REDLINER_DB_PATH", "").strip()
        self.db_path = Path(db_path or configured or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS deals (
                    deal_id TEXT PRIMARY KEY,
                    vendor_name TEXT NOT NULL DEFAULT '',
                    contract_path TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    iteration INTEGER NOT NULL DEFAULT 1,
                    max_iterations INTEGER NOT NULL DEFAULT 3,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS deal_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deal_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (deal_id) REFERENCES deals(deal_id)
                );

                CREATE INDEX IF NOT EXISTS idx_deal_events_deal
                    ON deal_events(deal_id, id);

                CREATE TABLE IF NOT EXISTS deal_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deal_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (deal_id) REFERENCES deals(deal_id)
                );

                CREATE INDEX IF NOT EXISTS idx_deal_snapshots_deal
                    ON deal_snapshots(deal_id, id);

                CREATE TABLE IF NOT EXISTS outbound_messages (
                    message_id TEXT PRIMARY KEY,
                    deal_id TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    thread_id TEXT,
                    in_reply_to TEXT,
                    references_json TEXT NOT NULL DEFAULT '[]',
                    provider TEXT,
                    provider_message_id TEXT,
                    sent_at TEXT NOT NULL,
                    FOREIGN KEY (deal_id) REFERENCES deals(deal_id)
                );

                CREATE INDEX IF NOT EXISTS idx_outbound_deal
                    ON outbound_messages(deal_id);
                CREATE INDEX IF NOT EXISTS idx_outbound_thread
                    ON outbound_messages(thread_id);
                """
            )

    def save(
        self,
        state: NegotiationDealState,
        *,
        event_type: str = "state_saved",
        actor: str = "system",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = _now()
        vendor_name = state.vendor_profile.company_name if state.vendor_profile else ""
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM deals WHERE deal_id = ?", (state.deal_id,)
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            connection.execute(
                """
                INSERT INTO deals (
                    deal_id, vendor_name, contract_path, status, iteration,
                    max_iterations, state_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deal_id) DO UPDATE SET
                    vendor_name = excluded.vendor_name,
                    contract_path = excluded.contract_path,
                    status = excluded.status,
                    iteration = excluded.iteration,
                    max_iterations = excluded.max_iterations,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    state.deal_id,
                    vendor_name,
                    state.source_contract_filename,
                    state.run_status,
                    state.iteration,
                    state.max_iterations,
                    state.model_dump_json(),
                    created_at,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO deal_events (deal_id, event_type, actor, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    state.deal_id,
                    event_type,
                    actor,
                    json.dumps(payload or {}, default=str),
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO deal_snapshots (deal_id, iteration, status, state_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    state.deal_id,
                    state.iteration,
                    state.run_status,
                    state.model_dump_json(),
                    now,
                ),
            )

    def get(self, deal_id: str) -> Optional[NegotiationDealState]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM deals WHERE deal_id = ?", (deal_id,)
            ).fetchone()
        if row is None:
            return None
        return NegotiationDealState.model_validate_json(row["state_json"])

    def list(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT deal_id, vendor_name, contract_path, status, iteration,
                       max_iterations, updated_at, state_json
                FROM deals ORDER BY updated_at DESC LIMIT ?
                """,
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            raw_state = item.pop("state_json", "{}")
            try:
                state = json.loads(raw_state)
            except (TypeError, ValueError):
                state = {}
            vendor = state.get("vendor_profile") or {}
            usage = state.get("llm_usage") or {}
            finance = state.get("finance_analysis") or {}
            item.update(
                {
                    "risk_tier": vendor.get("risk_tier"),
                    "utility": state.get("normalized_utility_score", 0.0),
                    "utility_available": finance.get("status") == "complete",
                    "requires_human_approval": state.get("requires_human_approval", False),
                    "llm_tokens": usage.get("total_tokens"),
                    "llm_cost": usage.get("cost_usd"),
                    "trace_id": state.get("trace_id"),
                    "langfuse_trace_url": state.get("langfuse_trace_url"),
                }
            )
            results.append(item)
        return results

    def history(self, deal_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Return immutable snapshots, oldest first, for audit/provenance."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT iteration, status, state_json, created_at
                FROM deal_snapshots WHERE deal_id = ?
                ORDER BY id ASC LIMIT ?
                """,
                (deal_id, max(1, min(int(limit), 200))),
            ).fetchall()
        return [
            {
                "iteration": row["iteration"],
                "status": row["status"],
                "created_at": row["created_at"],
                "state": json.loads(row["state_json"]),
            }
            for row in rows
        ]

    def events(self, deal_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_type, actor, payload_json, created_at
                FROM deal_events WHERE deal_id = ? ORDER BY id DESC LIMIT ?
                """,
                (deal_id, max(1, min(int(limit), 500))),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item.pop("payload_json"))
            except (TypeError, ValueError):
                item["payload"] = {}
            result.append(item)
        return result

    def record_outbound(
        self,
        *,
        message_id: str,
        deal_id: str,
        recipient: str,
        subject: str,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[List[str]] = None,
        provider: Optional[str] = None,
        provider_message_id: Optional[str] = None,
    ) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO outbound_messages (
                    message_id, deal_id, recipient, subject, thread_id,
                    in_reply_to, references_json, provider,
                    provider_message_id, sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    deal_id,
                    recipient,
                    subject,
                    thread_id,
                    in_reply_to,
                    json.dumps(references or []),
                    provider,
                    provider_message_id,
                    now,
                ),
            )

    def find_deal_by_reply(
        self,
        *,
        in_reply_to: Optional[str] = None,
        references: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
    ) -> Optional[str]:
        ids = [value for value in ([in_reply_to] + list(references or [])) if value]
        with self._connect() as connection:
            if ids:
                placeholders = ",".join("?" for _ in ids)
                row = connection.execute(
                    f"""
                    SELECT deal_id FROM outbound_messages
                    WHERE message_id IN ({placeholders})
                    ORDER BY sent_at DESC LIMIT 1
                    """,
                    ids,
                ).fetchone()
                if row:
                    return row["deal_id"]
            if thread_id:
                row = connection.execute(
                    """
                    SELECT deal_id FROM outbound_messages
                    WHERE thread_id = ? ORDER BY sent_at DESC LIMIT 1
                    """,
                    (thread_id,),
                ).fetchone()
                if row:
                    return row["deal_id"]
        return None

    def purge(self, retention_days: int) -> Dict[str, int]:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max(0, int(retention_days)))
        ).isoformat()
        with self._connect() as connection:
            event_count = connection.execute(
                "DELETE FROM deal_events WHERE created_at < ?", (cutoff,)
            ).rowcount
            snapshot_count = connection.execute(
                "DELETE FROM deal_snapshots WHERE created_at < ?", (cutoff,)
            ).rowcount
            message_count = connection.execute(
                "DELETE FROM outbound_messages WHERE sent_at < ?", (cutoff,)
            ).rowcount
        return {
            "events": event_count,
            "snapshots": snapshot_count,
            "outbound_messages": message_count,
        }
