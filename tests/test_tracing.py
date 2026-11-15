import os
from contextlib import contextmanager
from unittest.mock import patch

from services import tracing


def test_tracing_is_noop_without_keys():
    with patch.dict(
        os.environ,
        {
            "LANGFUSE_PUBLIC_KEY": "",
            "LANGFUSE_SECRET_KEY": "",
            "LANGFUSE_TRACING_ENABLED": "true",
        },
    ), patch.object(tracing, "_INITIALISED", False), patch.object(
        tracing, "_CLIENT", None
    ):
        assert tracing.tracing_enabled() is False
        with tracing.span("test.span", trace_id="a" * 32) as observation:
            observation.update(output={"ok": True})
        assert tracing.trace_url("a" * 32) is None
        tracing.flush()


def test_tracing_span_uses_configured_client():
    class FakeObservation:
        def __init__(self):
            self.calls = []

        def update(self, **kwargs):
            self.calls.append(kwargs)

    class FakeClient:
        def __init__(self):
            self.observation = FakeObservation()
            self.kwargs = None

        @contextmanager
        def start_as_current_observation(self, **kwargs):
            self.kwargs = kwargs
            yield self.observation

        def get_trace_url(self, trace_id=None):
            return f"https://langfuse.test/{trace_id}"

    fake = FakeClient()
    with patch.object(tracing, "_CLIENT", fake), patch.object(
        tracing, "_INITIALISED", True
    ):
        with tracing.span(
            "test.span",
            trace_id="b" * 32,
            model="test-model",
            usage_details={"input": 1},
        ) as observation:
            tracing.update(observation, output={"ok": True})
        assert tracing.trace_url("b" * 32) == f"https://langfuse.test/{'b' * 32}"

    assert fake.kwargs["trace_context"]["trace_id"] == "b" * 32
    assert fake.observation.calls
