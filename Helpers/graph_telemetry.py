"""Callback-style graph tracing and local audit persistence."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

TRACE_FILE = Path(__file__).resolve().parent / "graph_traces.jsonl"
TraceCallback = Callable[[Dict[str, Any]], None]


class GraphTelemetry:
    def __init__(self, trace_id: str, callback: Optional[TraceCallback] = None) -> None:
        self.trace_id = trace_id
        self.callback = callback

    def _notify(self, event: Dict[str, Any]) -> None:
        if self.callback:
            try:
                self.callback(event)
            except Exception:
                # Observability callbacks must not break contract processing.
                pass

    def emit(self, *, node: str, event: str, status: str, **details: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": self.trace_id,
            "span_id": uuid.uuid4().hex[:16],
            "node": node,
            "event": event,
            "status": status,
            **details,
        }
        TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_FILE.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, default=str) + "\n")
        self._notify(record)

    def run(self, node: str, fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        started = time.perf_counter()
        self._notify({"event": "node_started", "trace_id": self.trace_id, "node": node})
        try:
            output = fn()
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            self.emit(node=node, event="node_finished", status="error",
                      duration_ms=duration_ms, error_type=type(exc).__name__)
            self._notify({"event": "node_error", "trace_id": self.trace_id, "node": node,
                          "error_type": type(exc).__name__})
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        output_counts = {
            key: len(value)
            for key, value in output.items()
            if isinstance(value, (list, tuple, dict, set))
        }
        self.emit(node=node, event="node_finished", status="success",
                  duration_ms=duration_ms, output_keys=list(output), output_counts=output_counts)
        self._notify({"event": "node_finished", "trace_id": self.trace_id, "node": node,
                      "status": "success", "duration_ms": duration_ms,
                      "output_keys": list(output), "output_counts": output_counts})
        return output
