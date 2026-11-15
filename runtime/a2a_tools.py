"""CrewAI tool that calls the ADK Vendor Intelligence agent over A2A."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types.a2a_pb2 import (
    Message,
    Part,
    ROLE_USER,
    SendMessageConfiguration,
    SendMessageRequest,
    TASK_STATE_COMPLETED,
)
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

DEFAULT_A2A_URL = "http://127.0.0.1:8001"


class A2AVendorInput(BaseModel):
    vendor_name: str = Field(description="Vendor company name")


class A2AVendorTool(BaseTool):
    name: str = "a2a_vendor_intelligence"
    description: str = (
        "Ask the remote ADK Vendor Intelligence agent for a vendor risk profile "
        "using the A2A protocol. Use this for cross-framework due diligence."
    )
    args_schema: type[BaseModel] = A2AVendorInput

    def _run(self, vendor_name: str) -> str:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._run_async(vendor_name))
        import concurrent.futures
        import contextvars

        context = contextvars.copy_context()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(
                context.run, asyncio.run, self._run_async(vendor_name)
            ).result()

    async def _run_async(self, vendor_name: str) -> str:
        from services.tracing import span, update

        base_url = os.environ.get("A2A_VENDOR_URL", DEFAULT_A2A_URL).rstrip("/")
        timeout = float(os.environ.get("A2A_TIMEOUT_SECONDS", "20"))
        headers = {}
        if os.environ.get("A2A_SERVICE_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['A2A_SERVICE_TOKEN']}"
        with span(
            "a2a.vendor_intelligence",
            as_type="tool",
            input={"vendor_name": vendor_name, "endpoint": base_url},
            metadata={"protocol": "A2A"},
        ) as observation:
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as http:
                factory = ClientFactory(
                    ClientConfig(httpx_client=http, streaming=False)
                )
                client = await factory.create_from_url(base_url)
                request = SendMessageRequest(
                    message=Message(
                        message_id=uuid.uuid4().hex,
                        role=ROLE_USER,
                        parts=[Part(text=json.dumps({"vendor_name": vendor_name}))],
                    ),
                    configuration=SendMessageConfiguration(),
                )
                async for response in client.send_message(request):
                    payload = _response_payload(response)
                    if payload is not None:
                        update(observation, output={"risk_tier": payload.get("risk_tier")})
                        return json.dumps(payload, default=str)
        raise RuntimeError("A2A agent returned no result")


def _response_payload(response: Any) -> Dict[str, Any] | None:
    task = getattr(response, "task", None)
    if task is not None:
        if task.status.state != TASK_STATE_COMPLETED:
            raise RuntimeError(f"A2A task ended in state {task.status.state}")
        for artifact in task.artifacts:
            for part in artifact.parts:
                if part.text:
                    return json.loads(part.text)
        return None
    message = getattr(response, "message", None)
    if message is not None:
        for part in message.parts:
            if part.text:
                return json.loads(part.text)
    return None
