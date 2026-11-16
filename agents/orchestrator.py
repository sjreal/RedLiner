"""Main Orchestrator facade over the CrewAI crew and Google ADK workflow.

The runtime is intentionally framework-native:
- Google ADK drives parsing, legal/vendor analysis, trade-off checks and the
  human-approval decision through ADK agents.
- CrewAI runs the procurement, finance and email-writing crew.
- LangGraph is not used.

The public `process_incoming_deal` contract is kept for the FastAPI server,
the Gmail poller and existing callers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agents.email_writer import EmailWriterAgent
from agents.legal_redliner import LegalRedlinerAgent
from core.counteroffer import extract_counteroffer
from core.guardrails import scan_input
from core.models import Clause, OutboundEmailRequest, RedlineResult, VendorProfile
from core.state import NegotiationDealState
from core.store_factory import Repository, get_deal_repository
from Helpers.graph_telemetry import TraceCallback
from services.notifications import ReviewerNotifier
from services.tracing import event as trace_event
from services.tracing import flush as flush_traces
from services.tracing import span, trace_url, update
from subgraphs.human_approval import FeedbackAgent
from runtime.adk_runtime import AdkPipeline
from runtime.crew_runtime import CrewAIRuntime
from runtime.pipeline import deterministic_pipeline


class MainOrchestrator:
    """Share state between the ADK workflow and the CrewAI business crew."""

    def __init__(
        self,
        playbook_path: Optional[Path] = None,
        worker_url: Optional[str] = None,
        callback: Optional[TraceCallback] = None,
        repository: Optional[Repository] = None,
    ) -> None:
        self.playbook_path = playbook_path
        self.callback = callback
        self.legal_redliner = LegalRedlinerAgent(playbook_path)
        self.email_writer = EmailWriterAgent(worker_url)
        self.adk = AdkPipeline(playbook_path)
        self.crew = CrewAIRuntime()
        self.repository = repository or get_deal_repository()
        self.notifier = ReviewerNotifier()
        self.pipeline = self.adk.root

    def reload_playbook(self, new_path: Optional[Path] = None) -> None:
        self.playbook_path = new_path
        self.legal_redliner.reload_playbook(new_path)
        # Rebuild the ADK legal node with the new playbook path.
        self.adk = AdkPipeline(new_path)
        self.pipeline = self.adk.root

    def _blocked_state(
        self,
        *,
        deal_id: str,
        contract_path: Path,
        flags: List[str],
        trace_id: str,
    ) -> NegotiationDealState:
        state = NegotiationDealState(
            deal_id=deal_id,
            source_contract_filename=contract_path.name,
            contract_path=str(contract_path),
            run_status="BLOCKED_BY_GUARDRAIL",
            security_status="BLOCKED",
            security_flags=flags,
            guardrail_flags=flags,
            trace_id=trace_id,
            crew_status="not_run",
        )
        self.repository.save(
            state,
            event_type="guardrail_blocked",
            payload={"flags": flags},
        )
        return state

    def process_incoming_deal(
        self,
        deal_id: str,
        contract_path: Path,
        vendor_name: str,
        output_dir: Path,
        max_iterations: int = 3,
        email_context: str = "",
        offered_price: Optional[float] = None,
        target_price: Optional[float] = None,
        callback: Optional[TraceCallback] = None,
        iteration: int = 1,
        human_feedback: Optional[str] = None,
        counteroffer: Optional[Dict[str, Any]] = None,
    ) -> NegotiationDealState:
        contract_path = Path(contract_path)
        output_dir = Path(output_dir)
        trace_id = uuid.uuid4().hex
        input_guard = scan_input(email_context)
        if input_guard.blocked:
            return self._blocked_state(
                deal_id=deal_id,
                contract_path=contract_path,
                flags=input_guard.flags + input_guard.warnings,
                trace_id=trace_id,
            )

        if callback:
            callback({"event": "runtime_started", "trace_id": trace_id,
                      "frameworks": ["CrewAI", "Google ADK"]})

        adk_error: Optional[str] = None
        try:
            with span(
                "adk.pipeline",
                trace_id=trace_id,
                metadata={"deal_id": deal_id, "stage": "adk"},
                input={"contract": contract_path.name, "vendor": vendor_name},
            ) as adk_observation:
                adk_state = self.adk.run(
                    deal_id=deal_id,
                    contract_path=contract_path,
                    vendor_name=vendor_name,
                    output_dir=output_dir,
                    offered_price=offered_price,
                    target_price=target_price,
                    max_iterations=max_iterations,
                    trace_id=trace_id,
                )
                update(
                    adk_observation,
                    output={
                        "clauses": len(adk_state.get("parsed_clauses", [])),
                        "redlines": len(adk_state.get("redline_actions", [])),
                        "events": adk_state.get("adk_event_count", 0),
                    },
                    level="DEFAULT",
                )
            if adk_state.get("pipeline_error"):
                raise RuntimeError(adk_state["pipeline_error"])
            adk_used = True
        except Exception as exc:
            adk_error = f"{type(exc).__name__}: {exc}"
            adk_state = deterministic_pipeline(
                deal_id=deal_id,
                contract_path=contract_path,
                vendor_name=vendor_name,
                output_dir=output_dir,
                offered_price=offered_price,
                target_price=target_price,
                playbook_path=self.playbook_path,
            )
            adk_used = False
            if callback:
                callback({"event": "adk_fallback", "trace_id": trace_id,
                          "error_type": type(exc).__name__})

        clauses = [
            Clause.model_validate(item)
            for item in adk_state.get("parsed_clauses", [])
        ]
        redline_result = (
            RedlineResult.model_validate(adk_state["redline_result"])
            if adk_state.get("redline_result")
            else None
        )
        vendor_profile = (
            VendorProfile.model_validate(adk_state["vendor_profile"])
            if adk_state.get("vendor_profile")
            else None
        )
        if redline_result is None or vendor_profile is None:
            failed = NegotiationDealState(
                deal_id=deal_id,
                iteration=iteration,
                max_iterations=max_iterations,
                source_contract_filename=contract_path.name,
                contract_path=str(contract_path),
                output_dir=str(output_dir),
                parsed_clauses=clauses,
                run_status="ERROR",
                security_status="CLEAR",
                trace_id=trace_id,
                adk_event_count=int(adk_state.get("adk_event_count", 0)),
                pipeline_error=adk_state.get("pipeline_error") or adk_error or "Incomplete pipeline result",
                crew_status="not_run",
                review_feedback=human_feedback,
                counteroffer=counteroffer or {},
            )
            self.repository.save(failed, event_type="pipeline_error")
            return failed

        mcp_tools = []
        if adk_state.get("mcp_contract_used"):
            mcp_tools.append("contract_tools.parse_contract")
        if adk_state.get("mcp_vendor_used"):
            mcp_tools.append("vendor_tools.lookup_vendor")
        if adk_state.get("mcp_finance_used"):
            mcp_tools.append("finance_tools.propose_tradeoff")
        mcp_errors = [
            error
            for error in (
                adk_state.get("mcp_contract_error"),
                adk_state.get("mcp_vendor_error"),
                adk_state.get("mcp_finance_error"),
            )
            if error
        ]

        redline_actions = [action.model_dump(mode="json") for action in redline_result.actions]
        effective_offered = (
            offered_price if offered_price is not None else adk_state.get("offered_price")
        )
        effective_target = (
            target_price if target_price is not None else adk_state.get("target_price")
        )
        recipient_email = f"counsel@{vendor_profile.domain}"
        recipient_name = f"{vendor_profile.company_name} Legal Counsel"

        with span(
            "crewai.crew",
            trace_id=trace_id,
            metadata={"deal_id": deal_id, "stage": "crewai"},
            input={"vendor": vendor_profile.company_name, "redlines": len(redline_actions)},
        ) as crew_observation:
            crew_result = self.crew.run(
                contract_name=contract_path.stem,
                vendor_name=vendor_profile.company_name,
                risk_score=vendor_profile.risk_score,
                redline_actions=redline_actions,
                offered_price=effective_offered,
                target_price=effective_target,
                finance_analysis=adk_state.get("finance_analysis", {}),
                tradeoff_proposal=adk_state.get("tradeoff_proposal", {}),
                recipient_email=recipient_email,
                recipient_name=recipient_name,
                human_feedback=human_feedback or "",
                counteroffer=counteroffer,
            )
            update(
                crew_observation,
                output={
                    "status": crew_result.status,
                    "guardrail_flags": crew_result.guardrail_flags,
                },
                metadata={"usage": crew_result.usage},
            )

        with span(
            "email.draft",
            trace_id=trace_id,
            metadata={"deal_id": deal_id, "stage": "email"},
            input={"recipient": recipient_email},
        ) as email_observation:
            counter_email = self.email_writer.compose_counter_proposal(
                redline_result=redline_result,
                vendor=vendor_profile,
                recipient_email=recipient_email,
                recipient_name=recipient_name,
                draft_body=crew_result.email_body or None,
                draft_subject=crew_result.email_subject or None,
                deal_id=deal_id,
            )
            update(
                email_observation,
                output={"subject": counter_email.subject, "chars": len(counter_email.counter_proposal_body)},
            )

        procurement_plan = crew_result.procurement_plan or adk_state.get(
            "procurement_plan", {}
        )
        is_converged = bool(adk_state.get("is_converged", False))
        requires_review = bool(adk_state.get("requires_human_approval", False))

        if is_converged:
            run_status = "CONVERGED"
            convergence_reason = "no_open_redlines"
        elif iteration >= max_iterations:
            run_status = "MAX_ITERATIONS_REACHED"
            requires_review = True
            convergence_reason = "max_iterations"
        elif requires_review:
            run_status = "AWAITING_HUMAN_REVIEW"
            convergence_reason = "human_approval_required"
        else:
            run_status = adk_state.get("run_status", "DRAFT_READY")
            convergence_reason = "open_redlines"

        if not adk_used:
            run_status = f"{run_status}_ADK_FALLBACK"
        if crew_result.status in {"error", "guardrail_blocked"}:
            run_status = f"{run_status}_CREW_FALLBACK"

        state = NegotiationDealState(
            deal_id=deal_id,
            iteration=iteration,
            max_iterations=max_iterations,
            source_contract_filename=contract_path.name,
            contract_path=str(contract_path),
            output_dir=str(output_dir),
            parsed_clauses=clauses,
            redline_actions=redline_result.actions,
            redline_result=redline_result,
            vendor_profile=vendor_profile,
            is_converged=is_converged,
            requires_human_approval=requires_review,
            target_price=effective_target,
            offered_price=effective_offered,
            commercial_offer_price=adk_state.get("commercial_offer_price", effective_offered),
            contract_terms=adk_state.get("contract_terms", {}),
            normalized_utility_score=float(adk_state.get("normalized_utility_score", 0.0)),
            commercial_rounds=int(adk_state.get("commercial_rounds", 0)),
            human_review_summary=adk_state.get("human_review_summary"),
            counter_proposal_email=counter_email,
            run_status=run_status,
            security_status="CLEAR",
            security_flags=[],
            guardrail_flags=(
                input_guard.flags
                + [f"warning:{item}" for item in input_guard.warnings]
                + crew_result.guardrail_flags
            ),
            llm_status=crew_result.status,
            llm_usage=crew_result.usage,
            trace_id=trace_id,
            langfuse_trace_url=trace_url(trace_id),
            procurement_plan=procurement_plan,
            finance_analysis=adk_state.get("finance_analysis", {}),
            crew_finance_review=crew_result.finance_review,
            tradeoff_proposal=adk_state.get("tradeoff_proposal", {}),
            runtime_frameworks=["CrewAI", "Google ADK"],
            crew_status=crew_result.status,
            crew_error=crew_result.error,
            adk_event_count=int(adk_state.get("adk_event_count", 0)),
            pipeline_error=adk_error,
            review_feedback=human_feedback,
            convergence_reason=convergence_reason,
            counteroffer=counteroffer or {},
            mcp_tools_used=mcp_tools,
            mcp_errors=mcp_errors,
        )
        self.repository.save(
            state,
            event_type="pipeline_completed",
            payload={
                "iteration": iteration,
                "run_status": run_status,
                "convergence_reason": convergence_reason,
                "requires_human_approval": requires_review,
                "crew_status": crew_result.status,
                "mcp_tools_used": mcp_tools,
            },
        )
        if requires_review:
            notification = self.notifier.notify(state)
            if notification.get("status") != "skipped":
                self.repository.save(
                    state,
                    event_type="reviewer_notified",
                    payload=notification,
                )
        if callback:
            callback({"event": "runtime_finished", "trace_id": trace_id,
                      "adk_used": adk_used, "crew_status": crew_result.status})
        flush_traces()
        return state

    def get_deal(self, deal_id: str) -> Optional[NegotiationDealState]:
        return self.repository.get(deal_id)

    def list_deals(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.repository.list(limit)

    def find_deal_for_reply(
        self,
        *,
        in_reply_to: Optional[str] = None,
        references: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
        deal_reference: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve an inbound email to an existing deal, if it is a reply."""
        deal_id = self.repository.find_deal_by_reply(
            in_reply_to=in_reply_to,
            references=references,
            thread_id=thread_id,
        )
        if deal_id:
            return deal_id
        if deal_reference and self.repository.get(deal_reference):
            return deal_reference
        return None

    def record_outbound(
        self,
        email: OutboundEmailRequest,
        receipt: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist the sent message identity so later replies can be matched."""
        if not email.message_id or not email.deal_id:
            return
        receipt = receipt or {}
        response = receipt.get("response")
        response_id = response.get("id") if isinstance(response, dict) else None
        self.repository.record_outbound(
            message_id=email.message_id,
            deal_id=email.deal_id,
            recipient=email.recipient_email,
            subject=email.subject,
            thread_id=receipt.get("thread_id"),
            in_reply_to=email.in_reply_to,
            references=email.references,
            provider=receipt.get("provider"),
            provider_message_id=receipt.get("provider_message_id") or response_id,
        )

    def handle_vendor_reply(
        self,
        deal_id: str,
        text: str,
        *,
        subject: str = "",
        notes: str = "",
    ) -> NegotiationDealState:
        """Extract a reply and either start the next round or request review."""
        state = self.repository.get(deal_id)
        if state is None:
            raise KeyError(f"Deal not found: {deal_id}")
        extraction = extract_counteroffer(text, target_price=state.target_price)
        extraction_payload = extraction.model_dump(mode="json")
        extraction_payload["subject"] = subject
        extraction_payload["notes"] = notes

        if extraction.offered_price is None or extraction.confidence < 0.7:
            state.counteroffer = {
                "extraction": extraction_payload,
                "status": "NEEDS_HUMAN_REVIEW",
            }
            state.requires_human_approval = True
            state.run_status = "AWAITING_HUMAN_REVIEW"
            state.convergence_reason = "counteroffer_low_confidence"
            state.review_feedback = (
                f"Vendor reply could not be applied automatically: {subject}"
            )
            self.repository.save(
                state,
                event_type="counteroffer_needs_review",
                payload=extraction_payload,
            )
            return state

        updated = self.apply_counteroffer(
            deal_id,
            offered_price=float(extraction.offered_price),
            target_price=state.target_price,
            notes=notes or extraction.notes,
        )
        updated.counteroffer = {
            "extraction": extraction_payload,
            "status": "APPLIED",
        }
        self.repository.save(
            updated,
            event_type="vendor_reply_applied",
            payload=extraction_payload,
        )
        return updated

    def _contract_path(self, state: NegotiationDealState) -> Path:
        if state.contract_path:
            return Path(state.contract_path)
        candidates = [
            Path("data/sample_contracts") / state.source_contract_filename,
            Path("data/incoming") / state.source_contract_filename,
            Path("data/uploads") / state.source_contract_filename,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"Contract not found for deal {state.deal_id}")

    def decide(
        self,
        deal_id: str,
        decision: str,
        reviewer: str = "",
        notes: str = "",
        edited_clauses: Optional[List[Dict[str, Any]]] = None,
    ) -> NegotiationDealState:
        """Persist a human decision; reject/edit starts the next iteration."""
        state = self.repository.get(deal_id)
        if state is None:
            raise KeyError(f"Deal not found: {deal_id}")
        normalized = FeedbackAgent.process_decision(decision, notes)
        decision_value = normalized["decision"]
        state.human_decision = decision_value
        state.review_feedback = notes or state.review_feedback
        state.manual_edits = edited_clauses or state.manual_edits
        trace_event(
            "approval.decision",
            trace_id=state.trace_id,
            output={"decision": decision_value, "iteration": state.iteration},
            metadata={"reviewer": reviewer or "reviewer"},
        )

        if decision_value == "APPROVE":
            state.requires_human_approval = False
            state.is_converged = True
            state.convergence_reason = "human_approved"
            state.run_status = "APPROVED"
            self.repository.save(
                state,
                event_type="human_decision",
                actor=reviewer or "reviewer",
                payload={"decision": decision_value, "notes": notes},
            )
            return state

        if state.iteration >= state.max_iterations:
            state.requires_human_approval = True
            state.is_converged = False
            state.convergence_reason = "max_iterations"
            state.run_status = "MAX_ITERATIONS_REACHED"
            self.repository.save(
                state,
                event_type="human_decision",
                actor=reviewer or "reviewer",
                payload={"decision": decision_value, "notes": notes, "escalated": True},
            )
            return state

        next_state = self.process_incoming_deal(
            deal_id=state.deal_id,
            contract_path=self._contract_path(state),
            vendor_name=state.vendor_profile.company_name if state.vendor_profile else "",
            output_dir=Path(state.output_dir or "data/outputs"),
            max_iterations=state.max_iterations,
            offered_price=state.offered_price,
            target_price=state.target_price,
            iteration=state.iteration + 1,
            human_feedback=notes,
            counteroffer=state.counteroffer,
        )
        next_state.human_decision = decision_value
        next_state.review_feedback = notes
        next_state.manual_edits = edited_clauses or []
        self.repository.save(
            next_state,
            event_type="human_decision",
            actor=reviewer or "reviewer",
            payload={
                "decision": decision_value,
                "notes": notes,
                "new_iteration": next_state.iteration,
                "edited_clauses": edited_clauses or [],
            },
        )
        return next_state

    def apply_counteroffer(
        self,
        deal_id: str,
        offered_price: float,
        target_price: Optional[float] = None,
        notes: str = "",
    ) -> NegotiationDealState:
        """Apply a vendor counteroffer and start the next bounded iteration."""
        state = self.repository.get(deal_id)
        if state is None:
            raise KeyError(f"Deal not found: {deal_id}")
        if offered_price <= 0:
            raise ValueError("offered_price must be positive")
        if state.iteration >= state.max_iterations:
            state.requires_human_approval = True
            state.is_converged = False
            state.convergence_reason = "max_iterations"
            state.run_status = "MAX_ITERATIONS_REACHED"
            trace_event(
                "counteroffer.rejected",
                trace_id=state.trace_id,
                output={"reason": "max_iterations", "offered_price": offered_price},
            )
            self.repository.save(
                state,
                event_type="counteroffer_rejected",
                payload={"reason": "max_iterations", "offered_price": offered_price},
            )
            return state

        trace_event(
            "counteroffer.received",
            trace_id=state.trace_id,
            output={"offered_price": offered_price, "target_price": target_price},
        )
        counteroffer = {
            "offered_price": float(offered_price),
            "target_price": float(target_price or state.target_price or 0.0),
            "notes": notes,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        next_state = self.process_incoming_deal(
            deal_id=state.deal_id,
            contract_path=self._contract_path(state),
            vendor_name=state.vendor_profile.company_name if state.vendor_profile else "",
            output_dir=Path(state.output_dir or "data/outputs"),
            max_iterations=state.max_iterations,
            offered_price=float(offered_price),
            target_price=target_price or state.target_price,
            iteration=state.iteration + 1,
            human_feedback=notes or state.review_feedback,
            counteroffer=counteroffer,
        )
        next_state.human_decision = None
        next_state.counteroffer = counteroffer
        self.repository.save(
            next_state,
            event_type="counteroffer_applied",
            payload=counteroffer,
        )
        return next_state
