"""Deterministic input/output guardrails around LLM calls."""

from __future__ import annotations

import os
import re
from typing import List

from pydantic import BaseModel, Field

_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions\b", re.I),
    re.compile(r"\b(reveal|print|expose)\s+(the\s+)?(system prompt|api key|secrets?)\b", re.I),
    re.compile(r"\bact\s+as\s+(a\s+)?(system|developer)\b", re.I),
    re.compile(r"<\s*/?\s*(system|assistant|developer)\s*>", re.I),
    re.compile(r"\bdisregard\s+(your|all)\s+(rules|instructions)\b", re.I),
)
_SECRET_PATTERNS = (
    re.compile(r"\b(?:api[_-]?key|secret|password)\s*[:=]\s*\S{6,}", re.I),
    re.compile(r"\b(?:sk|oc_sk|re)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
_TOXIC_PATTERNS = (
    re.compile(r"\b(?:kill|hurt|attack)\s+(you|them|him|her)\b", re.I),
    re.compile(r"\byou\s+(?:are|r)\s+(?:an?\s+)?(?:idiot|moron|stupid)\b", re.I),
    re.compile(r"\b(?:fuck|shit|bastard)\b", re.I),
)
_PII_PATTERNS = (
    ("email_address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("phone_number", re.compile(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
)
_OUTPUT_LEAK_PATTERNS = (
    re.compile(r"\bsystem prompt\b", re.I),
    re.compile(r"\bapi[_-]?key\b", re.I),
    re.compile(r"\bchain[-\s]?of[-\s]?thought\b", re.I),
)


class GuardrailResult(BaseModel):
    blocked: bool = False
    flags: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


def _enabled() -> bool:
    return os.environ.get("LLM_GUARDRAILS_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def inspect_untrusted_text(text: str) -> List[str]:
    """Backward-compatible injection-only check."""
    if not text:
        return []
    return [
        f"prompt_injection_pattern_{index + 1}"
        for index, pattern in enumerate(_INJECTION_PATTERNS)
        if pattern.search(text)
    ]


def scan_input(text: str, *, max_chars: int = 100_000) -> GuardrailResult:
    """Scan untrusted text before it reaches a model or an agent."""
    if not _enabled() or not text:
        return GuardrailResult()

    flags: List[str] = []
    warnings: List[str] = []
    if len(text) > max_chars:
        flags.append("input_too_large")
    for index, pattern in enumerate(_INJECTION_PATTERNS):
        if pattern.search(text):
            flags.append(f"prompt_injection_pattern_{index + 1}")
    for index, pattern in enumerate(_SECRET_PATTERNS):
        if pattern.search(text):
            flags.append(f"secret_pattern_{index + 1}")
    for index, pattern in enumerate(_TOXIC_PATTERNS):
        if pattern.search(text):
            flags.append(f"abusive_language_pattern_{index + 1}")
    for label, pattern in _PII_PATTERNS:
        if pattern.search(text):
            warnings.append(f"pii_{label}")

    return GuardrailResult(
        blocked=bool(flags),
        flags=sorted(set(flags)),
        warnings=sorted(set(warnings)),
    )


def scan_output(text: str, *, max_chars: int = 50_000) -> GuardrailResult:
    """Scan model output before it is persisted or sent to a vendor."""
    if not _enabled() or not text:
        return GuardrailResult()

    flags: List[str] = []
    warnings: List[str] = []
    if len(text) > max_chars:
        flags.append("output_too_large")
    for index, pattern in enumerate(_INJECTION_PATTERNS):
        if pattern.search(text):
            flags.append(f"output_injection_pattern_{index + 1}")
    for index, pattern in enumerate(_SECRET_PATTERNS):
        if pattern.search(text):
            flags.append(f"output_secret_pattern_{index + 1}")
    for index, pattern in enumerate(_OUTPUT_LEAK_PATTERNS):
        if pattern.search(text):
            flags.append(f"output_leak_pattern_{index + 1}")
    for index, pattern in enumerate(_TOXIC_PATTERNS):
        if pattern.search(text):
            flags.append(f"output_abusive_pattern_{index + 1}")
    for label, pattern in _PII_PATTERNS:
        if pattern.search(text):
            warnings.append(f"output_pii_{label}")

    return GuardrailResult(
        blocked=bool(flags),
        flags=sorted(set(flags)),
        warnings=sorted(set(warnings)),
    )
