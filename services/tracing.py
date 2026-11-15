"""Optional Langfuse Cloud tracing with a local no-op fallback."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional

try:
    from langfuse import Langfuse
except Exception:  # pragma: no cover - dependency missing in a minimal deploy
    Langfuse = None  # type: ignore[assignment]


class _NoopObservation:
    def update(self, **_: Any) -> "_NoopObservation":
        return self

    def end(self, **_: Any) -> None:
        return None

    def score(self, **_: Any) -> None:
        return None

    def score_trace(self, **_: Any) -> None:
        return None


_CLIENT: Optional[Any] = None
_INITIALISED = False


def tracing_enabled() -> bool:
    if os.environ.get("LANGFUSE_TRACING_ENABLED", "true").lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
        and os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    )


def get_client() -> Optional[Any]:
    global _CLIENT, _INITIALISED
    if _INITIALISED:
        return _CLIENT
    _INITIALISED = True
    if not tracing_enabled() or Langfuse is None:
        _CLIENT = None
        return None
    try:
        _CLIENT = Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            base_url=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            environment=os.environ.get("LANGFUSE_ENVIRONMENT", "demo"),
            release=os.environ.get("LANGFUSE_RELEASE", "redliner-demo"),
        )
    except Exception:
        _CLIENT = None
    return _CLIENT


@contextmanager
def span(
    name: str,
    *,
    trace_id: Optional[str] = None,
    as_type: str = "span",
    input: Any = None,
    output: Any = None,
    metadata: Optional[dict] = None,
    model: Optional[str] = None,
    usage_details: Optional[dict] = None,
    cost_details: Optional[dict] = None,
) -> Iterator[Any]:
    """Create a nested Langfuse observation or yield a no-op object."""
    client = get_client()
    if client is None:
        yield _NoopObservation()
        return

    kwargs = {
        "name": name,
        "as_type": as_type,
        "input": input,
        "output": output,
        "metadata": metadata or {},
    }
    if trace_id:
        kwargs["trace_context"] = {"trace_id": trace_id}
    if model:
        kwargs["model"] = model
    if usage_details:
        kwargs["usage_details"] = usage_details
    if cost_details:
        kwargs["cost_details"] = cost_details

    try:
        manager = client.start_as_current_observation(**kwargs)
    except Exception:
        # Tracing must never break contract processing.
        yield _NoopObservation()
        return
    with manager as observation:
        yield observation


def update(observation: Any, **kwargs: Any) -> None:
    try:
        observation.update(**kwargs)
    except Exception:
        pass


def flush() -> None:
    client = get_client()
    if client is not None:
        try:
            client.flush()
        except Exception:
            pass


def event(name: str, *, trace_id: Optional[str] = None, **kwargs: Any) -> None:
    client = get_client()
    if client is None:
        return
    try:
        if trace_id:
            kwargs["trace_context"] = {"trace_id": trace_id}
        client.create_event(name=name, **kwargs)
    except Exception:
        pass


def trace_url(trace_id: Optional[str]) -> Optional[str]:
    client = get_client()
    if client is None or not trace_id:
        return None
    try:
        return client.get_trace_url(trace_id=trace_id)
    except Exception:
        return None
