"""ADK Vendor Intelligence agent exposed over A2A.

Run with:
    PYTHONPATH=. uv run python -m uvicorn a2a_servers.vendor_agent:app --port 8001
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, AsyncGenerator

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from subgraphs.vendor_information import VendorInformationSubgraph


def _request_text(ctx: Any) -> str:
    content = getattr(ctx, "user_content", None)
    if content is None:
        return ""
    return "\n".join(
        part.text for part in (content.parts or []) if getattr(part, "text", None)
    ).strip()


def _vendor_name(text: str) -> str:
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            value = payload.get("vendor_name") or payload.get("vendor")
            if value:
                return str(value)
    except (TypeError, ValueError):
        pass
    match = re.search(r"(?:vendor(?:_name)?\s*[=:]\s*)(.+)", text, re.I)
    return (match.group(1) if match else text).strip()[:200] or "Vendor"


class VendorIntelligenceA2AAgent(BaseAgent):
    """Deterministic ADK agent that returns a vendor risk profile as JSON."""

    async def _run_async_impl(
        self, ctx: Any
    ) -> AsyncGenerator[Event, None]:
        vendor_name = _vendor_name(_request_text(ctx))
        profile = VendorInformationSubgraph().assess_vendor(vendor_name)
        payload = {
            "agent": "RedLiner Vendor Intelligence",
            "vendor_name": profile.company_name,
            "domain": profile.domain,
            "risk_score": profile.risk_score,
            "risk_tier": profile.risk_tier.value,
            "sanction_pep_status": profile.sanction_pep_status.value,
            "flags": profile.flags,
        }
        yield Event(
            author=self.name,
            content=types.Content(
                role="model",
                parts=[types.Part(text=json.dumps(payload))],
            ),
        )


root_agent = VendorIntelligenceA2AAgent(
    name="vendor_intelligence",
    description="Look up vendor risk, sanctions/PEP status and risk tier.",
)

A2A_HOST = os.environ.get("A2A_HOST", "127.0.0.1")
A2A_PORT = int(os.environ.get("A2A_PORT", "8001"))
A2A_PROTOCOL = os.environ.get("A2A_PROTOCOL", "http")
app = to_a2a(
    root_agent,
    host=A2A_HOST,
    port=A2A_PORT,
    protocol=A2A_PROTOCOL,
)


class ServiceTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        expected = os.environ.get("A2A_SERVICE_TOKEN", "").strip()
        if expected and request.method != "OPTIONS":
            header = request.headers.get("authorization", "")
            if header != f"Bearer {expected}":
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


app.add_middleware(ServiceTokenMiddleware)
