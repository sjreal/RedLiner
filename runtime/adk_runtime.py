"""Google ADK workflow for parsing, analysis, trade-offs and approval."""

from __future__ import annotations

import asyncio
import uuid
import warnings
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional

from google.adk.agents import (
    BaseAgent,
    LoopAgent,
    ParallelAgent,
    SequentialAgent,
)
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import PrivateAttr

from core.contract_terms import extract_contract_terms
from core.models import (
    ParsedDocument,
    RedlineResult,
    TradeoffProposalResult,
    VendorProfile,
)
from runtime.mcp_client import call_tool_async, mcp_enabled
from runtime.pipeline import (
    build_review_summary,
    parse_contract,
    prepare_source_docx,
    review_required,
    run_commercial_review,
    run_legal_review,
    run_vendor_review,
)

APP_NAME = "redliner"
ANALYSIS_PARALLEL = "analysis_team"
PIPELINE_NAME = "redliner_pipeline"


def _delta(**values: Any) -> Dict[str, Any]:
    return values


class _StateNode(BaseAgent):
    """Small async ADK node that writes serializable values to session state."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        original = cls.__dict__.get("_run_async_impl")
        if original is None:
            return

        async def traced(self: Any, ctx: Any):
            from services.tracing import span

            with span(
                f"adk.{self.name}",
                as_type="agent",
                metadata={"agent": self.name},
            ):
                async for event in original(self, ctx):
                    yield event

        cls._run_async_impl = traced

    def _event(self, **values: Any) -> Event:
        return Event(
            author=self.name,
            actions=EventActions(state_delta=_delta(**values)),
        )


class DocumentParserNode(_StateNode):
    _parser = PrivateAttr()

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        from subgraphs.document_parser import DocumentParserSubgraph

        self._parser = DocumentParserSubgraph()

    async def _run_async_impl(
        self, ctx: Any
    ) -> AsyncGenerator[Event, None]:
        mcp_used = False
        mcp_error = None
        try:
            contract_path = Path(ctx.session.state["contract_path"])
            if mcp_enabled():
                try:
                    payload = await call_tool_async(
                        "contract_tools.py",
                        "parse_contract",
                        {"path": str(contract_path)},
                    )
                    parsed = ParsedDocument.model_validate(payload)
                    mcp_used = True
                except Exception as exc:
                    mcp_error = f"{type(exc).__name__}: {exc}"
                    parsed = self._parser.execute(contract_path)
            else:
                parsed = self._parser.execute(contract_path)
            yield self._event(
                parsed_document=parsed.model_dump(mode="json"),
                parsed_clauses=[c.model_dump(mode="json") for c in parsed.clauses],
                mcp_contract_used=mcp_used,
                mcp_contract_error=mcp_error,
                run_status="PARSED",
            )
        except Exception as exc:
            yield self._event(
                pipeline_error=f"{type(exc).__name__}: {exc}",
                run_status="ERROR",
            )


class ContractTermsNode(_StateNode):
    """Extract price, payment, liability and term context from the parsed clauses."""

    async def _run_async_impl(
        self, ctx: Any
    ) -> AsyncGenerator[Event, None]:
        try:
            parsed = ParsedDocument.model_validate(
                ctx.session.state["parsed_document"]
            )
            terms = extract_contract_terms(parsed)
            state = ctx.session.state
            delta: Dict[str, Any] = {
                "contract_terms": terms.model_dump(mode="json"),
                "run_status": "TERMS_EXTRACTED",
            }
            if terms.offered_price is not None:
                if state.get("offered_price") is None:
                    delta["offered_price"] = terms.offered_price
                if state.get("commercial_offer_price") is None:
                    delta["commercial_offer_price"] = terms.offered_price
                if state.get("target_price") is None:
                    # The default procurement policy asks for a 10% discount;
                    # mark this as a policy target, not a contract fact.
                    delta["target_price"] = round(terms.offered_price * 0.9, 2)
                    delta["target_price_source"] = "default_10pct_discount"
            yield self._event(**delta)
        except Exception as exc:
            yield self._event(
                pipeline_error=f"{type(exc).__name__}: {exc}",
                run_status="ERROR",
            )


class LegalReviewNode(_StateNode):
    _playbook_path = PrivateAttr()

    def __init__(self, playbook_path: Optional[Path] = None, **data: Any) -> None:
        super().__init__(**data)
        self._playbook_path = playbook_path

    async def _run_async_impl(
        self, ctx: Any
    ) -> AsyncGenerator[Event, None]:
        try:
            state = ctx.session.state
            contract_path = Path(state["contract_path"])
            parsed = ParsedDocument.model_validate(state["parsed_document"])
            output_dir = Path(state["output_dir"])
            source = prepare_source_docx(
                contract_path,
                parsed,
                output_dir,
                state["deal_id"],
            )
            result = run_legal_review(
                source,
                output_dir,
                parsed.clauses,
                contract_path.stem,
                self._playbook_path,
            )
            yield self._event(
                redline_result=result.model_dump(mode="json"),
                redline_actions=[a.model_dump(mode="json") for a in result.actions],
                run_status="REDLINED",
            )
        except Exception as exc:
            yield self._event(
                pipeline_error=f"{type(exc).__name__}: {exc}",
                run_status="ERROR",
            )


class VendorIntelligenceNode(_StateNode):
    async def _run_async_impl(
        self, ctx: Any
    ) -> AsyncGenerator[Event, None]:
        mcp_used = False
        mcp_error = None
        try:
            vendor_name = ctx.session.state["vendor_name"]
            if mcp_enabled():
                try:
                    payload = await call_tool_async(
                        "vendor_tools.py",
                        "lookup_vendor",
                        {"vendor_name": vendor_name},
                    )
                    profile = VendorProfile.model_validate(payload)
                    mcp_used = True
                except Exception as exc:
                    mcp_error = f"{type(exc).__name__}: {exc}"
                    profile = run_vendor_review(vendor_name)
            else:
                profile = run_vendor_review(vendor_name)
            yield self._event(
                vendor_profile=profile.model_dump(mode="json"),
                mcp_vendor_used=mcp_used,
                mcp_vendor_error=mcp_error,
                run_status="VENDOR_ASSESSED",
            )
        except Exception as exc:
            yield self._event(
                pipeline_error=f"{type(exc).__name__}: {exc}",
                run_status="ERROR",
            )


class ConcessionNode(_StateNode):
    """Move the simulated buyer offer toward target between loop rounds."""

    async def _run_async_impl(
        self, ctx: Any
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        offered = state.get("commercial_offer_price", state.get("offered_price"))
        target = state.get("target_price")
        rounds = int(state.get("commercial_rounds", 0)) + 1
        if offered is not None and target is not None and float(offered) > float(target):
            # A bounded 5% concession per round; the deterministic tradeoff
            # engine still owns utility and guardrail checks.
            next_offer = max(float(target), float(offered) * 0.95)
            yield self._event(
                commercial_offer_price=next_offer,
                commercial_rounds=rounds,
                run_status="COMMERCIAL_LOOP",
            )
        else:
            yield self._event(
                commercial_rounds=rounds,
                run_status="COMMERCIAL_LOOP",
            )


class TradeoffNode(_StateNode):
    async def _run_async_impl(
        self, ctx: Any
    ) -> AsyncGenerator[Event, None]:
        try:
            state = ctx.session.state
            vendor = VendorProfile.model_validate(state["vendor_profile"])
            offered = state.get("commercial_offer_price", state.get("offered_price"))
            target = state.get("target_price")
            finance, tradeoff, utility = run_commercial_review(
                offered,
                target,
                vendor.risk_score,
            )
            mcp_finance_used = False
            mcp_finance_error = None
            if mcp_enabled() and offered is not None and target is not None:
                try:
                    payload = await call_tool_async(
                        "finance_tools.py",
                        "propose_tradeoff",
                        {
                            "offered_price": float(offered),
                            "target_price": float(target),
                            "vendor_risk_score": vendor.risk_score,
                        },
                    )
                    mcp_tradeoff = TradeoffProposalResult.model_validate(payload)
                    tradeoff = mcp_tradeoff.model_dump(mode="json")
                    utility = mcp_tradeoff.normalized_utility_score
                    finance = {
                        **finance,
                        "within_guardrails": mcp_tradeoff.passed_guardrails,
                    }
                    mcp_finance_used = True
                except Exception as exc:
                    mcp_finance_error = f"{type(exc).__name__}: {exc}"
            yield self._event(
                finance_analysis=finance,
                tradeoff_proposal=tradeoff,
                normalized_utility_score=utility or 0.0,
                mcp_finance_used=mcp_finance_used,
                mcp_finance_error=mcp_finance_error,
                run_status="COMMERCIAL_REVIEWED",
            )
        except Exception as exc:
            yield self._event(
                pipeline_error=f"{type(exc).__name__}: {exc}",
                run_status="ERROR",
            )


class ApprovalGateNode(_StateNode):
    async def _run_async_impl(
        self, ctx: Any
    ) -> AsyncGenerator[Event, None]:
        try:
            state = ctx.session.state
            redline = RedlineResult.model_validate(state["redline_result"])
            vendor = VendorProfile.model_validate(state["vendor_profile"])
            needs_review = review_required(
                redline,
                vendor,
                state.get("finance_analysis", {}),
                state.get("tradeoff_proposal", {}),
            )
            converged = len(redline.actions) == 0 and not needs_review
            yield self._event(
                requires_human_approval=needs_review,
                is_converged=converged,
                run_status="AWAITING_HUMAN_REVIEW" if needs_review else "DRAFT_READY",
            )
        except Exception as exc:
            yield self._event(
                pipeline_error=f"{type(exc).__name__}: {exc}",
                run_status="ERROR",
            )


class ReviewSummaryNode(_StateNode):
    async def _run_async_impl(
        self, ctx: Any
    ) -> AsyncGenerator[Event, None]:
        try:
            state = ctx.session.state
            redline = RedlineResult.model_validate(state["redline_result"])
            vendor = VendorProfile.model_validate(state["vendor_profile"])
            summary = build_review_summary(
                Path(state["contract_path"]).stem,
                redline,
                vendor,
                float(state.get("normalized_utility_score", 0.0)),
            )
            yield self._event(
                human_review_summary=summary,
                run_status=state.get("run_status", "DRAFT_READY"),
            )
        except Exception as exc:
            yield self._event(
                pipeline_error=f"{type(exc).__name__}: {exc}",
                run_status="ERROR",
            )


class AdkPipeline:
    """Build and run the ADK agent graph."""

    def __init__(self, playbook_path: Optional[Path] = None) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            parser = DocumentParserNode(name="document_parser")
            terms = ContractTermsNode(name="contract_terms")
            legal = LegalReviewNode(
                name="legal_review",
                playbook_path=playbook_path,
            )
            vendor = VendorIntelligenceNode(name="vendor_intelligence")
            analysis = ParallelAgent(
                name=ANALYSIS_PARALLEL,
                sub_agents=[legal, vendor],
            )
            concession = ConcessionNode(name="concession_strategy")
            tradeoff = TradeoffNode(name="tradeoff_engine")
            commercial_loop = LoopAgent(
                name="commercial_loop",
                max_iterations=2,
                sub_agents=[concession, tradeoff],
            )
            approval = ApprovalGateNode(name="approval_gate")
            summary = ReviewSummaryNode(name="deal_summary")
            self.root = SequentialAgent(
                name=PIPELINE_NAME,
                sub_agents=[parser, terms, analysis, commercial_loop, approval, summary],
            )

    def run(
        self,
        *,
        deal_id: str,
        contract_path: Path,
        vendor_name: str,
        output_dir: Path,
        offered_price: Optional[float] = None,
        target_price: Optional[float] = None,
        max_iterations: int = 1,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return asyncio.run(
            self._run_async(
                deal_id=deal_id,
                contract_path=contract_path,
                vendor_name=vendor_name,
                output_dir=output_dir,
                offered_price=offered_price,
                target_price=target_price,
                max_iterations=max_iterations,
                trace_id=trace_id,
            )
        )

    async def _run_async(
        self,
        *,
        deal_id: str,
        contract_path: Path,
        vendor_name: str,
        output_dir: Path,
        offered_price: Optional[float],
        target_price: Optional[float],
        max_iterations: int,
        trace_id: Optional[str],
    ) -> Dict[str, Any]:
        session_id = f"{deal_id}-{uuid.uuid4().hex[:10]}"
        session_service = InMemorySessionService()
        initial_state = {
            "deal_id": deal_id,
            "trace_id": trace_id or uuid.uuid4().hex,
            "contract_path": str(Path(contract_path)),
            "vendor_name": vendor_name,
            "output_dir": str(Path(output_dir)),
            "offered_price": offered_price,
            "commercial_offer_price": offered_price,
            "target_price": target_price,
            "contract_terms": {},
            "max_iterations": max_iterations,
            "run_status": "RUNNING",
            "pipeline_error": None,
            "finance_analysis": {},
            "tradeoff_proposal": {},
            "normalized_utility_score": 0.0,
            "requires_human_approval": False,
            "is_converged": False,
            "mcp_contract_used": False,
            "mcp_vendor_used": False,
            "mcp_contract_error": None,
            "mcp_vendor_error": None,
            "mcp_finance_used": False,
            "mcp_finance_error": None,
            "commercial_rounds": 0,
        }
        await session_service.create_session(
            app_name=APP_NAME,
            user_id="redliner",
            session_id=session_id,
            state=initial_state,
        )
        runner = Runner(
            agent=self.root,
            app_name=APP_NAME,
            session_service=session_service,
        )
        event_count = 0
        async for _event in runner.run_async(
            user_id="redliner",
            session_id=session_id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text="Process this contract through the RedLiner pipeline.")],
            ),
        ):
            event_count += 1

        session = await session_service.get_session(
            app_name=APP_NAME,
            user_id="redliner",
            session_id=session_id,
        )
        result = dict(session.state)
        result["adk_event_count"] = event_count
        return result
