"""Deterministic pipeline steps shared by ADK nodes and the fallback path."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core.models import (
    Clause,
    FinanceAnalysisResult,
    ParsedDocument,
    RedlineResult,
    TradeoffProposalResult,
    VendorProfile,
)
from subgraphs.document_parser import DocumentParserSubgraph
from subgraphs.human_approval import InterruptionGate, SummaryAgent
from subgraphs.tradeoff_engine import TradeoffEngineSubgraph


def parse_contract(contract_path: Path) -> ParsedDocument:
    return DocumentParserSubgraph().execute(Path(contract_path))


def prepare_source_docx(
    contract_path: Path,
    parsed: ParsedDocument,
    output_dir: Path,
    deal_id: str,
) -> Path:
    source = Path(contract_path)
    if source.suffix.lower() != ".pdf":
        return source
    import docx

    output_dir.mkdir(parents=True, exist_ok=True)
    temp_docx = output_dir / f"temp_{source.stem}_{deal_id}.docx"
    document = docx.Document()
    document.add_heading(source.stem.replace("_", " ").title(), 0)
    for clause in parsed.clauses:
        document.add_heading(clause.heading, level=1)
        document.add_paragraph(clause.text)
    document.save(str(temp_docx))
    return temp_docx


def run_legal_review(
    source_path: Path,
    output_dir: Path,
    clauses: list[Clause],
    contract_name: str,
    playbook_path: Optional[Path] = None,
) -> RedlineResult:
    from agents.legal_redliner import LegalRedlinerAgent

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{Path(contract_name).stem}_redlined.docx"
    result = LegalRedlinerAgent(playbook_path).generate_redlined_docx(
        source_docx_path=Path(source_path),
        output_docx_path=output_path,
        clauses=clauses,
        contract_name=Path(contract_name).stem,
    )
    return RedlineResult.model_validate(result.model_dump())


def run_vendor_review(vendor_name: str) -> VendorProfile:
    from agents.vendor_intelligence import VendorIntelligenceAgent

    profile = VendorIntelligenceAgent().evaluate_counterparty(vendor_name)
    return VendorProfile.model_validate(profile.model_dump())


def run_commercial_review(
    offered_price: Optional[float],
    target_price: Optional[float],
    risk_score: float,
) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[float]]:
    if offered_price is None or target_price is None:
        skipped = {"status": "skipped_missing_price_context"}
        return skipped, skipped.copy(), None

    from agents.finance_compliance_risk import FinanceComplianceRiskAgent

    finance = FinanceComplianceRiskAgent().evaluate_boundaries(
        deal_cost=float(offered_price),
        target_cost=float(target_price),
        payment_term_days=60,
        regulatory_risk_score=risk_score,
    )
    tradeoff = TradeoffEngineSubgraph().execute(
        offered_price=float(offered_price),
        target_price=float(target_price),
        vendor_risk_score=risk_score,
    )
    finance_model = FinanceAnalysisResult.model_validate(finance)
    tradeoff_model = TradeoffProposalResult.model_validate(tradeoff)
    return (
        finance_model.model_dump(),
        tradeoff_model.model_dump(),
        tradeoff_model.normalized_utility_score,
    )


def review_required(
    redline_result: RedlineResult,
    vendor: VendorProfile,
    finance: Dict[str, Any],
    tradeoff: Dict[str, Any],
) -> bool:
    needs_review = InterruptionGate.should_interrupt(
        critical_violations=redline_result.critical_count,
        vendor_risk_score=vendor.risk_score,
    )
    if finance.get("status") == "complete":
        needs_review = needs_review or not bool(finance.get("is_approved"))
    if tradeoff.get("status") == "complete":
        needs_review = needs_review or not bool(tradeoff.get("passed_guardrails"))
    return needs_review


def build_review_summary(
    contract_name: str,
    redline_result: RedlineResult,
    vendor: VendorProfile,
    utility_score: float = 0.0,
) -> Dict[str, Any]:
    return SummaryAgent.generate_deal_summary(
        contract_name=Path(contract_name).stem,
        actions=redline_result.actions,
        vendor_profile=vendor,
        utility_score=utility_score,
    )


def deterministic_pipeline(
    *,
    deal_id: str,
    contract_path: Path,
    vendor_name: str,
    output_dir: Path,
    offered_price: Optional[float],
    target_price: Optional[float],
    playbook_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Sequential fallback used only if an ADK node fails unexpectedly."""
    parsed = parse_contract(contract_path)
    source = prepare_source_docx(contract_path, parsed, output_dir, deal_id)
    redline = run_legal_review(
        source,
        output_dir,
        parsed.clauses,
        contract_path.stem,
        playbook_path,
    )
    vendor = run_vendor_review(vendor_name)
    finance, tradeoff, utility = run_commercial_review(
        offered_price,
        target_price,
        vendor.risk_score,
    )
    needs_review = review_required(redline, vendor, finance, tradeoff)
    summary = build_review_summary(
        contract_path.stem,
        redline,
        vendor,
        utility or 0.0,
    )
    return {
        "parsed_document": parsed.model_dump(mode="json"),
        "parsed_clauses": [clause.model_dump(mode="json") for clause in parsed.clauses],
        "vendor_profile": vendor.model_dump(mode="json"),
        "redline_result": redline.model_dump(mode="json"),
        "redline_actions": [action.model_dump(mode="json") for action in redline.actions],
        "finance_analysis": finance,
        "tradeoff_proposal": tradeoff,
        "normalized_utility_score": utility or 0.0,
        "requires_human_approval": needs_review,
        "is_converged": len(redline.actions) == 0 and not needs_review,
        "run_status": "AWAITING_HUMAN_REVIEW" if needs_review else "DRAFT_READY",
        "human_review_summary": summary,
        "pipeline_error": None,
        "adk_event_count": 0,
    }
