"""PostgreSQL/Supabase deal repository.

Set DATABASE_URL to a PostgreSQL connection string (Supabase database URLs are
supported). The SQLite repository remains the zero-configuration local default.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from core.state import NegotiationDealState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresDealRepository:
    def __init__(self, dsn: Optional[str] = None) -> None:
        self.dsn = dsn or os.environ.get("DATABASE_URL", "")
        if not self.dsn:
            raise ValueError("DATABASE_URL is required for PostgresDealRepository")
        self._initialize()

    def _connect(self):
        return connect(self.dsn, row_factory=dict_row, connect_timeout=15)

    def _initialize(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS deals (
                    deal_id TEXT PRIMARY KEY,
                    vendor_name TEXT NOT NULL DEFAULT '',
                    contract_path TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    iteration INTEGER NOT NULL DEFAULT 1,
                    max_iterations INTEGER NOT NULL DEFAULT 3,
                    state_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deal_events (
                    id BIGSERIAL PRIMARY KEY,
                    deal_id TEXT NOT NULL REFERENCES deals(deal_id),
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT '',
                    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_deal_events_deal
                    ON deal_events(deal_id, id);
                CREATE TABLE IF NOT EXISTS deal_snapshots (
                    id BIGSERIAL PRIMARY KEY,
                    deal_id TEXT NOT NULL REFERENCES deals(deal_id),
                    iteration INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    state_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_deal_snapshots_deal
                    ON deal_snapshots(deal_id, id);
                CREATE TABLE IF NOT EXISTS outbound_messages (
                    message_id TEXT PRIMARY KEY,
                    deal_id TEXT NOT NULL REFERENCES deals(deal_id),
                    recipient TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    thread_id TEXT,
                    in_reply_to TEXT,
                    references_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                    provider TEXT,
                    provider_message_id TEXT,
                    sent_at TIMESTAMPTZ NOT NULL
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
        now = datetime.now(timezone.utc)
        vendor_name = state.vendor_profile.company_name if state.vendor_profile else ""
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO deals (
                    deal_id, vendor_name, contract_path, status, iteration,
                    max_iterations, state_json, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (deal_id) DO UPDATE SET
                    vendor_name = EXCLUDED.vendor_name,
                    contract_path = EXCLUDED.contract_path,
                    status = EXCLUDED.status,
                    iteration = EXCLUDED.iteration,
                    max_iterations = EXCLUDED.max_iterations,
                    state_json = EXCLUDED.state_json,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    state.deal_id,
                    vendor_name,
                    state.source_contract_filename,
                    state.run_status,
                    state.iteration,
                    state.max_iterations,
                    Jsonb(state.model_dump(mode="json")),
                    now,
                    now,
                ),
            )
            cursor.execute(
                """
                INSERT INTO deal_events (deal_id, event_type, actor, payload_json, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (state.deal_id, event_type, actor, Jsonb(payload or {}), now),
            )
            cursor.execute(
                """
                INSERT INTO deal_snapshots (deal_id, iteration, status, state_json, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    state.deal_id,
                    state.iteration,
                    state.run_status,
                    Jsonb(state.model_dump(mode="json")),
                    now,
                ),
            )

    def get(self, deal_id: str) -> Optional[NegotiationDealState]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT state_json FROM deals WHERE deal_id = %s", (deal_id,)
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return NegotiationDealState.model_validate(row["state_json"])

    def list(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT deal_id, vendor_name, contract_path, status, iteration,
                       max_iterations, updated_at, state_json
                FROM deals ORDER BY updated_at DESC LIMIT %s
                """,
                (max(1, min(int(limit), 200)),),
            )
            results = []
            for row in cursor.fetchall():
                item = dict(row)
                state = item.pop("state_json", {}) or {}
                vendor = state.get("vendor_profile") or {}
                usage = state.get("llm_usage") or {}
                item.update(
                    {
                        "risk_tier": vendor.get("risk_tier"),
                        "utility": state.get("normalized_utility_score", 0.0),
                        "requires_human_approval": state.get(
                            "requires_human_approval", False
                        ),
                        "llm_tokens": usage.get("total_tokens"),
                        "llm_cost": usage.get("cost_usd"),
                        "trace_id": state.get("trace_id"),
                        "langfuse_trace_url": state.get("langfuse_trace_url"),
                    }
                )
                results.append(item)
            return results

    def history(self, deal_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT iteration, status, state_json, created_at
                FROM deal_snapshots WHERE deal_id = %s ORDER BY id ASC LIMIT %s
                """,
                (deal_id, max(1, min(int(limit), 200))),
            )
            return [
                {
                    "iteration": row["iteration"],
                    "status": row["status"],
                    "created_at": row["created_at"].isoformat(),
                    "state": row["state_json"],
                }
                for row in cursor.fetchall()
            ]

    def events(self, deal_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_type, actor, payload_json, created_at
                FROM deal_events WHERE deal_id = %s ORDER BY id DESC LIMIT %s
                """,
                (deal_id, max(1, min(int(limit), 500))),
            )
            return [
                {
                    "event_type": row["event_type"],
                    "actor": row["actor"],
                    "payload": row["payload_json"],
                    "created_at": row["created_at"].isoformat(),
                }
                for row in cursor.fetchall()
            ]

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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO outbound_messages (
                    message_id, deal_id, recipient, subject, thread_id,
                    in_reply_to, references_json, provider,
                    provider_message_id, sent_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO NOTHING
                """,
                (
                    message_id,
                    deal_id,
                    recipient,
                    subject,
                    thread_id,
                    in_reply_to,
                    Jsonb(references or []),
                    provider,
                    provider_message_id,
                    datetime.now(timezone.utc),
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
        with self._connect() as connection, connection.cursor() as cursor:
            if ids:
                cursor.execute(
                    """
                    SELECT deal_id FROM outbound_messages
                    WHERE message_id = ANY(%s) OR message_id = %s
                    ORDER BY sent_at DESC LIMIT 1
                    """,
                    (ids, in_reply_to),
                )
                row = cursor.fetchone()
                if row:
                    return row["deal_id"]
            if thread_id:
                cursor.execute(
                    "SELECT deal_id FROM outbound_messages WHERE thread_id = %s ORDER BY sent_at DESC LIMIT 1",
                    (thread_id,),
                )
                row = cursor.fetchone()
                if row:
                    return row["deal_id"]
        return None

    def purge(self, retention_days: int) -> Dict[str, int]:
        days = max(0, int(retention_days))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM deal_events WHERE created_at < %s", (cutoff,)
            )
            event_count = cursor.rowcount
            cursor.execute(
                "DELETE FROM deal_snapshots WHERE created_at < %s", (cutoff,)
            )
            snapshot_count = cursor.rowcount
            cursor.execute(
                "DELETE FROM outbound_messages WHERE sent_at < %s", (cutoff,)
            )
            message_count = cursor.rowcount
        return {
            "events": event_count,
            "snapshots": snapshot_count,
            "outbound_messages": message_count,
        }
