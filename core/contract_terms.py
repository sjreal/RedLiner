"""Extract commercial terms from parsed contract clauses."""

from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, Field

from core.models import Clause, ParsedDocument

_WORD_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "thirty-six": 36,
    "forty": 40,
    "forty-five": 45,
    "sixty": 60,
    "ninety": 90,
}
_PRICE = re.compile(r"(?:\$|usd)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(k|m)?", re.I)
_NET = re.compile(r"\bnet\s*(\d{1,3})\b", re.I)
_TERM_MONTHS = re.compile(r"\b(\d{1,3})\s*months?\b", re.I)
_TERM_PAREN = re.compile(r"\((\d{1,3})\)\s*months?\b", re.I)
_TERM_WORDS = re.compile(
    r"\b(" + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True)) + r")\s+months?\b",
    re.I,
)
_LIABILITY_DAYS = re.compile(
    r"\b(?:last|preceding|previous)\s+(\d{1,3}|[a-z-]+)\s+days?\b", re.I
)
_LIABILITY_MONTHS = re.compile(
    r"\b(?:last|preceding|previous)\s+(\d{1,3}|[a-z-]+)\s+months?\b", re.I
)
_CAP_FEE_MONTHS = re.compile(
    r"\b(\d{1,3})\s*months?\s*(?:of\s*)?(?:fees|charges)\b", re.I
)
_LIABILITY_AMOUNT = re.compile(
    r"(?:liability|cap|aggregate)\D{0,40}(?:\$|usd)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(k|m)?",
    re.I,
)
_SLA = re.compile(r"\b(service credits?|sla credits?|uptime|availability)\b", re.I)


class ContractTerms(BaseModel):
    offered_price: Optional[float] = Field(default=None, ge=0.0)
    currency: str = "USD"
    payment_terms_days: Optional[int] = Field(default=None, ge=0, le=365)
    liability_cap: Optional[float] = Field(default=None, ge=0.0)
    liability_cap_basis: Optional[str] = None
    initial_term_months: Optional[int] = Field(default=None, ge=0, le=1200)
    sla_summary: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)


def _number(value: str) -> Optional[int]:
    value = (value or "").strip().lower()
    if value.isdigit():
        return int(value)
    return _WORD_NUMBERS.get(value)


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


def _clause_text(parsed: ParsedDocument) -> List[tuple[Clause, str]]:
    return [(clause, clause.text or "") for clause in parsed.clauses]


def extract_contract_terms(parsed: ParsedDocument) -> ContractTerms:
    """Conservative extraction from typed clauses; no invented values."""
    evidence: List[str] = []
    offered_price = None
    payment_terms = None
    liability_basis = None
    liability_cap = None
    term_months = None
    sla_summary = None

    for clause, text in _clause_text(parsed):
        if clause.clause_type.value == "PAYMENT_TERMS":
            match = _NET.search(text)
            if match:
                payment_terms = int(match.group(1))
                evidence.append(f"{clause.heading}: Net {payment_terms}")
            price_match = _PRICE.search(text)
            if price_match and offered_price is None:
                offered_price = _amount(price_match.group(1), price_match.group(2))
                evidence.append(f"{clause.heading}: {price_match.group(0)}")

        if clause.clause_type.value == "LIABILITY_CAP":
            days = _LIABILITY_DAYS.search(text)
            months = _LIABILITY_MONTHS.search(text)
            fee_months = _CAP_FEE_MONTHS.search(text)
            amount = _LIABILITY_AMOUNT.search(text)
            if days:
                liability_basis = f"last {days.group(1)} days of fees"
                evidence.append(f"{clause.heading}: {days.group(0)}")
            elif months:
                liability_basis = f"last {months.group(1)} months of fees"
                evidence.append(f"{clause.heading}: {months.group(0)}")
            elif fee_months:
                liability_basis = f"{fee_months.group(1)} months of fees"
                evidence.append(f"{clause.heading}: {fee_months.group(0)}")
            elif amount:
                liability_cap = _amount(amount.group(1), amount.group(2))
                liability_basis = "fixed amount"
                evidence.append(f"{clause.heading}: {amount.group(0)}")

        if clause.clause_type.value == "TERMINATION" and term_months is None:
            match = _TERM_PAREN.search(text) or _TERM_MONTHS.search(text)
            if match:
                term_months = int(match.group(1))
                evidence.append(f"{clause.heading}: {match.group(0)}")
            else:
                words = _TERM_WORDS.search(text)
                if words:
                    term_months = _number(words.group(1))
                    if term_months is not None:
                        evidence.append(f"{clause.heading}: {words.group(0)}")

        if clause.clause_type.value == "DATA_PRIVACY_SECURITY" and sla_summary is None:
            match = _SLA.search(text)
            if match:
                sla_summary = match.group(0)
                evidence.append(f"{clause.heading}: {match.group(0)}")

    found = sum(
        value is not None
        for value in (offered_price, payment_terms, liability_basis, term_months)
    )
    confidence = min(0.95, 0.25 + found * 0.15)
    return ContractTerms(
        offered_price=offered_price,
        payment_terms_days=payment_terms,
        liability_cap=liability_cap,
        liability_cap_basis=liability_basis,
        initial_term_months=term_months,
        sla_summary=sla_summary,
        confidence=confidence,
        evidence=evidence,
    )
