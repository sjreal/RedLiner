"""Pydantic contracts exchanged between the CrewAI agents."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ProcurementDecision(BaseModel):
    target_unit_price: Optional[float] = Field(default=None, ge=0.0)
    concession_plan: str = ""
    priorities: List[str] = Field(default_factory=list)
    approval_recommendation: Literal["approve", "review", "reject"] = "review"
    rationale: str = ""


class FinanceDecision(BaseModel):
    approved: bool = False
    utility_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    hard_stop_flags: List[str] = Field(default_factory=list)
    rationale: str = ""


class EmailDraft(BaseModel):
    subject: str = ""
    body: str = ""


class CrewResult(BaseModel):
    status: str = "disabled"
    procurement_plan: dict = Field(default_factory=dict)
    finance_review: dict = Field(default_factory=dict)
    email_subject: str = ""
    email_body: str = ""
    error: Optional[str] = None
    usage: dict = Field(default_factory=dict)
    mcp_tools_available: List[str] = Field(default_factory=list)
    guardrail_flags: List[str] = Field(default_factory=list)
