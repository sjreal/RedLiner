"""Extract vendor counteroffer terms from email text.

The deterministic pass is deliberately conservative. An ambiguous reply is
returned with low confidence and no price so the workflow can ask a human rather
than inventing a concession.
"""

from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, Field

_PRICE = re.compile(
    r"(?:(?:\$|usd)\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(k|m)?\s*(?:usd|dollars)?",
    re.I,
)
_NET = re.compile(r"\bnet\s*(\d{2,3})\b", re.I)
_DAYS = re.compile(r"\b(\d{1,3})\s*(?:calendar\s*)?days?\b", re.I)
_CAP_MONTHS = re.compile(r"\b(\d{1,2})\s*months?\s*(?:of\s*)?(?:fees|charges)\b", re.I)
_CAP_X = re.compile(r"\b(\d+(?:\.\d+)?)\s*x\s*(?:fees|annual\s*fees)\b", re.I)
_CAP_AMOUNT = re.compile(
    r"(?:liability|cap|aggregate)\D{0,40}(?:\$|usd)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(k|m)?",
    re.I,
)


class CounterofferExtraction(BaseModel):
    offered_price: Optional[float] = Field(default=None, ge=0.0)
    payment_terms_days: Optional[int] = Field(default=None, ge=0, le=365)
    liability_cap: Optional[float] = Field(default=None, ge=0.0)
    liability_cap_basis: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    notes: str = ""


def _amount(number: str, suffix: Optional[str]) -> Optional[float]:
    try:
        value = float(number.replace(",", ""))
    except ValueError:
        return None
    suffix = (suffix or "").lower()
    if suffix == "k":
        value *= 1_000
    elif suffix == "m":
        value *= 1_000_000
    return value


def extract_counteroffer(
    text: str,
    *,
    target_price: Optional[float] = None,
) -> CounterofferExtraction:
    """Extract the obvious price/payment/cap terms from a vendor reply."""
    text = (text or "").strip()
    if not text:
        return CounterofferExtraction(notes="Empty vendor reply")

    evidence: List[str] = []
    prices: List[float] = []
    for match in _PRICE.finditer(text):
        # Ignore times/dates and tiny numbers that are not plausible deal prices.
        value = _amount(match.group(1), match.group(2))
        raw = match.group(0).strip()
        has_currency_or_scale = raw.lower().startswith(("$", "usd")) or bool(
            match.group(2)
        )
        if value is not None and value >= 100 and (
            has_currency_or_scale or value >= 10_000
        ):
            prices.append(value)
            evidence.append(raw)

    offered_price = None
    if prices:
        if target_price is not None:
            offered_price = next(
                (price for price in prices if abs(price - target_price) > 0.01),
                prices[0],
            )
        else:
            offered_price = prices[0]

    payment_terms = None
    net_match = _NET.search(text)
    if net_match:
        payment_terms = int(net_match.group(1))
        evidence.append(net_match.group(0))
    else:
        days_match = _DAYS.search(text)
        if days_match:
            payment_terms = int(days_match.group(1))
            evidence.append(days_match.group(0))

    liability_cap = None
    liability_basis = None
    months_match = _CAP_MONTHS.search(text)
    if months_match:
        liability_cap = float(months_match.group(1)) * (target_price or 1.0)
        liability_basis = f"{months_match.group(1)} months of fees"
        evidence.append(months_match.group(0))
    else:
        x_match = _CAP_X.search(text)
        if x_match:
            liability_cap = float(x_match.group(1)) * (target_price or 1.0)
            liability_basis = f"{x_match.group(1)}x fees"
            evidence.append(x_match.group(0))
        else:
            amount_match = _CAP_AMOUNT.search(text)
            if amount_match:
                liability_cap = _amount(amount_match.group(1), amount_match.group(2))
                liability_basis = "fixed amount"
                evidence.append(amount_match.group(0))

    found = sum(
        value is not None for value in (offered_price, payment_terms, liability_cap)
    )
    confidence = {0: 0.15, 1: 0.55, 2: 0.8, 3: 0.9}[found]
    if offered_price is None:
        confidence = min(confidence, 0.35)

    return CounterofferExtraction(
        offered_price=offered_price,
        payment_terms_days=payment_terms,
        liability_cap=liability_cap,
        liability_cap_basis=liability_basis,
        confidence=confidence,
        evidence=evidence,
        notes="Deterministic extraction; human review required below 0.7 confidence.",
    )
