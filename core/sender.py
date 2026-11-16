"""Sender identity and signature normalization for outbound email."""

from __future__ import annotations

import os
import re

DEFAULT_SENDER_NAME = "Siddharth Jain"
DEFAULT_SENDER_COMPANY = "BML Munjal University"


def sender_identity() -> tuple[str, str]:
    name = (
        os.environ.get("REDLINER_SENDER_NAME", DEFAULT_SENDER_NAME).strip()
        or DEFAULT_SENDER_NAME
    )
    company = (
        os.environ.get("REDLINER_SENDER_COMPANY", DEFAULT_SENDER_COMPANY).strip()
        or DEFAULT_SENDER_COMPANY
    )
    return name, company


def signature_block() -> str:
    name, company = sender_identity()
    return f"Best regards,\n{name}\n{company}"


def ensure_sender_signature(body: str) -> str:
    """Replace any existing sign-off with the configured sender signature."""
    text = (body or "").strip()
    name, company = sender_identity()
    if not text:
        return signature_block()

    lowered = text.lower()
    if name.lower() in lowered and company.lower() in lowered:
        return text

    signoffs = list(
        re.finditer(
            r"\n\s*(best|kind|warm|sincerely|regards)\b",
            text,
            re.IGNORECASE,
        )
    )
    if signoffs:
        text = text[: signoffs[-1].start()].rstrip()

    return f"{text}\n\n{signature_block()}"
