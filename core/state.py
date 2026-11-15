from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from core.models import Clause, RedlineAction, VendorProfile, RedlineResult, OutboundEmailRequest


class NegotiationDealState(BaseModel):
    """
    Master state schema for the CrewAI + Google ADK negotiation workflow.
    Main Orchestrator shares this state between the ADK pipeline and CrewAI crew.
    """
    deal_id: str
    iteration: int = 1
    max_iterations: int = 5
    is_converged: bool = False
    requires_human_approval: bool = False
    human_decision: Optional[str] = None  # "APPROVE", "REJECT", "MANUAL_EDIT"

    # Document details
    source_contract_filename: str
    parsed_clauses: List[Clause] = Field(default_factory=list)

    # Redlining & Risk
    redline_actions: List[RedlineAction] = Field(default_factory=list)
    redline_result: Optional[RedlineResult] = None
    vendor_profile: Optional[VendorProfile] = None

    # Tradeoffs & Financials (PDF Subgraph 3.c)
    target_price: Optional[float] = None
    offered_price: Optional[float] = None
    commercial_offer_price: Optional[float] = None
    contract_terms: Dict[str, Any] = Field(default_factory=dict)
    target_payment_terms: str = "Net 60"
    normalized_utility_score: float = 0.0

    # Outbound counter-proposal email
    counter_proposal_email: Optional[OutboundEmailRequest] = None
    audit_logs: List[Dict[str, Any]] = Field(default_factory=list)

    # Execution, safety, and observability metadata
    run_status: str = "COMPLETED"
    security_status: str = "CLEAR"
    security_flags: List[str] = Field(default_factory=list)
    guardrail_flags: List[str] = Field(default_factory=list)
    human_review_summary: Optional[Dict[str, Any]] = None
    llm_status: str = "disabled"
    llm_usage: Dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None
    langfuse_trace_url: Optional[str] = None
    procurement_plan: Dict[str, Any] = Field(default_factory=dict)
    finance_analysis: Dict[str, Any] = Field(default_factory=dict)
    crew_finance_review: Dict[str, Any] = Field(default_factory=dict)
    tradeoff_proposal: Dict[str, Any] = Field(default_factory=dict)
    runtime_frameworks: List[str] = Field(default_factory=lambda: ["CrewAI", "Google ADK"])
    crew_status: str = "disabled"
    crew_error: Optional[str] = None
    adk_event_count: int = 0
    commercial_rounds: int = 0
    pipeline_error: Optional[str] = None

    # Persistence / HITL / convergence
    contract_path: Optional[str] = None
    output_dir: Optional[str] = None
    review_feedback: Optional[str] = None
    manual_edits: List[Dict[str, Any]] = Field(default_factory=list)
    convergence_reason: Optional[str] = None
    counteroffer: Dict[str, Any] = Field(default_factory=dict)
    mcp_tools_used: List[str] = Field(default_factory=list)
    mcp_errors: List[str] = Field(default_factory=list)
