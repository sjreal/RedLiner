"""Structured final deal report for API and Markdown export."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.models import Clause, RedlineAction, VendorProfile
from core.state import NegotiationDealState


class ApprovalRecord(BaseModel):
    event_type: str
    actor: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class SnapshotRecord(BaseModel):
    iteration: int
    status: str
    created_at: str


class ReportEmail(BaseModel):
    recipient: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    message_id: Optional[str] = None


class DealReport(BaseModel):
    report_version: str = "1.0"
    deal_id: str
    contract_name: str
    generated_at: str
    run_status: str
    iteration: int
    max_iterations: int
    is_converged: bool
    requires_human_approval: bool
    convergence_reason: Optional[str] = None
    vendor: Optional[VendorProfile] = None
    contract_terms: Dict[str, Any] = Field(default_factory=dict)
    offered_price: Optional[float] = None
    target_price: Optional[float] = None
    commercial_offer_price: Optional[float] = None
    normalized_utility_score: float = 0.0
    clauses: List[Clause] = Field(default_factory=list)
    redlines: List[RedlineAction] = Field(default_factory=list)
    finance: Dict[str, Any] = Field(default_factory=dict)
    tradeoff: Dict[str, Any] = Field(default_factory=dict)
    procurement_plan: Dict[str, Any] = Field(default_factory=dict)
    human_review_summary: Dict[str, Any] = Field(default_factory=dict)
    email: ReportEmail = Field(default_factory=ReportEmail)
    approvals: List[ApprovalRecord] = Field(default_factory=list)
    history: List[SnapshotRecord] = Field(default_factory=list)
    llm_usage: Dict[str, Any] = Field(default_factory=dict)
    guardrail_flags: List[str] = Field(default_factory=list)
    mcp_tools_used: List[str] = Field(default_factory=list)
    runtime_frameworks: List[str] = Field(default_factory=list)
    trace_id: Optional[str] = None
    langfuse_trace_url: Optional[str] = None


def build_deal_report(
    state: NegotiationDealState,
    *,
    events: Optional[List[Dict[str, Any]]] = None,
    history: Optional[List[Dict[str, Any]]] = None,
) -> DealReport:
    email = state.counter_proposal_email
    approval_events = [
        ApprovalRecord.model_validate(event)
        for event in (events or [])
        if event.get("event_type") in {"human_decision", "counteroffer_applied", "veto"}
    ]
    snapshots = [
        SnapshotRecord(
            iteration=int(item.get("iteration", 0)),
            status=str(item.get("status", "")),
            created_at=str(item.get("created_at", "")),
        )
        for item in (history or [])
    ]
    return DealReport(
        deal_id=state.deal_id,
        contract_name=state.source_contract_filename,
        generated_at=datetime.now(timezone.utc).isoformat(),
        run_status=state.run_status,
        iteration=state.iteration,
        max_iterations=state.max_iterations,
        is_converged=state.is_converged,
        requires_human_approval=state.requires_human_approval,
        convergence_reason=state.convergence_reason,
        vendor=state.vendor_profile,
        contract_terms=state.contract_terms,
        offered_price=state.offered_price,
        target_price=state.target_price,
        commercial_offer_price=state.commercial_offer_price,
        normalized_utility_score=state.normalized_utility_score,
        clauses=state.parsed_clauses,
        redlines=state.redline_actions,
        finance=state.finance_analysis,
        tradeoff=state.tradeoff_proposal,
        procurement_plan=state.procurement_plan,
        human_review_summary=state.human_review_summary or {},
        email=ReportEmail(
            recipient=email.recipient_email if email else None,
            subject=email.subject if email else None,
            body=email.counter_proposal_body if email else None,
            message_id=email.message_id if email else None,
        ),
        approvals=approval_events,
        history=snapshots,
        llm_usage=state.llm_usage,
        guardrail_flags=state.guardrail_flags,
        mcp_tools_used=state.mcp_tools_used,
        runtime_frameworks=state.runtime_frameworks,
        trace_id=state.trace_id,
        langfuse_trace_url=state.langfuse_trace_url,
    )


def _cell(value: Any) -> str:
    return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")


def report_to_markdown(report: DealReport) -> str:
    lines = [
        f"# RedLiner Deal Report — {report.deal_id}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Contract | {_cell(report.contract_name)} |",
        f"| Status | {_cell(report.run_status)} |",
        f"| Iteration | {report.iteration}/{report.max_iterations} |",
        f"| Converged | {report.is_converged} |",
        f"| Human approval required | {report.requires_human_approval} |",
        f"| Convergence reason | {_cell(report.convergence_reason)} |",
        f"| Runtime | {_cell(', '.join(report.runtime_frameworks))} |",
        f"| Trace ID | {_cell(report.trace_id)} |",
        f"| Langfuse trace | {_cell(report.langfuse_trace_url)} |",
        "",
        "## Vendor",
        "",
        f"- **Name:** {_cell(report.vendor.company_name if report.vendor else 'Unknown')}",
        f"- **Risk tier:** {_cell(report.vendor.risk_tier.value if report.vendor else 'UNKNOWN')}",
        f"- **Risk score:** {_cell(report.vendor.risk_score if report.vendor else '—')}",
        f"- **Sanctions/PEP:** {_cell(report.vendor.sanction_pep_status.value if report.vendor else 'UNKNOWN')}",
        "",
        "## Contract terms",
        "",
        "| Term | Value |",
        "|---|---|",
    ]
    for key, value in report.contract_terms.items():
        lines.append(f"| {_cell(key)} | {_cell(value)} |")
    if not report.contract_terms:
        lines.append("| _No terms extracted_ | — |")

    lines.extend(
        [
            "",
            "## Financials",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Offered price | {_cell(report.offered_price)} |",
            f"| Target price | {_cell(report.target_price)} |",
            f"| Commercial offer | {_cell(report.commercial_offer_price)} |",
            f"| Utility score | {_cell(report.normalized_utility_score)} |",
            f"| Finance approved | {_cell(report.finance.get('is_approved') if report.finance else '—')} |",
            f"| Tradeoff terms | {_cell(report.tradeoff.get('proposed_terms') if report.tradeoff else '—')} |",
            "",
            "## Redlines",
            "",
            "| Severity | Clause | Rule | Replacement |",
            "|---|---|---|---|",
        ]
    )
    for action in report.redlines:
        lines.append(
            "| {severity} | {clause} | {rule} | {replacement} |".format(
                severity=_cell(action.severity.value),
                clause=_cell(action.clause_type.value),
                rule=_cell(action.rule_name),
                replacement=_cell(action.replacement_text[:300]),
            )
        )
    if not report.redlines:
        lines.append("| — | — | — | _No redlines_ |")

    lines.extend(
        [
            "",
            "## Human review",
            "",
            _cell(
                report.human_review_summary.get("summary_text")
                or "No review summary."
            ),
            "",
            "## Approvals and iterations",
            "",
            "| Event | Actor | Iteration/Status |",
            "|---|---|---|",
        ]
    )
    for approval in report.approvals:
        lines.append(
            f"| {_cell(approval.event_type)} | {_cell(approval.actor)} | {_cell(approval.payload)} |"
        )
    for snapshot in report.history:
        lines.append(
            f"| snapshot | — | {snapshot.iteration} / {_cell(snapshot.status)} |"
        )
    if not report.approvals and not report.history:
        lines.append("| — | — | — |")

    lines.extend(
        [
            "",
            "## Cost / usage",
            "",
            "```json",
            json.dumps(report.llm_usage, indent=2, default=str),
            "```",
            "",
            "## Guardrails",
            "",
            ", ".join(report.guardrail_flags) or "No flags recorded",
            "",
            "## MCP tools",
            "",
            ", ".join(report.mcp_tools_used) or "None recorded",
            "",
        ]
    )
    return "\n".join(lines)
