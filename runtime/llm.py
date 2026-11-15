"""OpenCode Go model adapters for CrewAI and Google ADK."""

from __future__ import annotations

import os
import uuid
from typing import Optional

DEFAULT_BASE_URL = "https://opencode.ai/inference/go/openai/v1"


def opencode_configured() -> bool:
    return bool(os.environ.get("OPENCODE_API_KEY", "").strip())


def _model_name() -> str:
    return os.environ.get("OPENCODE_MODEL", "glm-5.3-flash").strip()


def _base_url() -> str:
    return os.environ.get("OPENCODE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _headers() -> dict[str, str]:
    return {"x-opencode-session": uuid.uuid4().hex}


def build_crewai_llm():
    """Build the CrewAI LLM against OpenCode's OpenAI-compatible endpoint."""
    if not opencode_configured():
        return None
    from crewai import LLM

    return LLM(
        model=f"openai/{_model_name()}",
        custom_openai=True,
        base_url=_base_url(),
        api_key=os.environ["OPENCODE_API_KEY"],
        default_headers=_headers(),
        temperature=0.2,
        max_tokens=2500,
    )


def build_adk_model():
    """Build an ADK OpenAILlm against the same OpenCode endpoint.

    OpenCode Go requires a stable session header for routing. Passing a
    preconfigured AsyncOpenAI client lets ADK use that header.
    """
    if not opencode_configured():
        return None
    from google.adk.integrations.openai import OpenAILlm
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.environ["OPENCODE_API_KEY"],
        base_url=_base_url(),
        default_headers=_headers(),
    )
    return OpenAILlm(model=_model_name(), client=client, max_tokens=2000)
