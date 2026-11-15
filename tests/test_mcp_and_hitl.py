import json
import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agents.orchestrator import MainOrchestrator
from core.deal_store import DealRepository
from runtime.adk_runtime import AdkPipeline
from runtime.crew_tools import VendorLookupTool
from runtime.mcp_client import call_tool
from server.app import app, orchestrator as app_orchestrator

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DOCX = BASE_DIR / "data" / "sample_contracts" / "vendor_saas_agreement.docx"
OUTPUT_DIR = BASE_DIR / "data" / "outputs"


def test_mcp_servers_expose_real_tools():
    with patch.dict(os.environ, {"MCP_ENABLED": "true"}):
        parsed = call_tool(
            "contract_tools.py",
            "parse_contract",
            {"path": str(SAMPLE_DOCX)},
        )
        vendor = call_tool(
            "vendor_tools.py",
            "lookup_vendor",
            {"vendor_name": "ApexCloud Enterprise Ltd"},
        )
        utility = call_tool(
            "finance_tools.py",
            "utility_score",
            {"unit_price": 120000, "target_price": 100000, "payment_terms_days": 60},
        )
        crew_tool_result = json.loads(
            VendorLookupTool()._run("ApexCloud Enterprise Ltd")
        )
    assert len(parsed["clauses"]) >= 7
    assert vendor["risk_tier"] == "LOW"
    assert 0.0 <= utility["utility_score"] <= 1.0
    assert crew_tool_result["risk_tier"] == "LOW"


def test_adk_uses_contract_and_vendor_mcp_servers():
    with patch.dict(os.environ, {"MCP_ENABLED": "true"}):
        result = AdkPipeline().run(
            deal_id="MCP-ADK-TEST",
            contract_path=SAMPLE_DOCX,
            vendor_name="ApexCloud Enterprise Ltd",
            output_dir=OUTPUT_DIR,
        )
    assert result["mcp_contract_used"] is True
    assert result["mcp_vendor_used"] is True
    assert result["mcp_contract_error"] is None
    assert result["mcp_vendor_error"] is None


def test_orchestrator_records_mcp_tools_used(tmp_path):
    with patch.dict(os.environ, {"MCP_ENABLED": "true"}):
        orchestrator = MainOrchestrator(
            repository=DealRepository(tmp_path / "deals.db")
        )
        state = orchestrator.process_incoming_deal(
            deal_id="MCP-ORCH-TEST",
            contract_path=SAMPLE_DOCX,
            vendor_name="ApexCloud Enterprise Ltd",
            output_dir=OUTPUT_DIR,
        )
    assert "contract_tools.parse_contract" in state.mcp_tools_used
    assert "vendor_tools.lookup_vendor" in state.mcp_tools_used
    assert state.mcp_errors == []


def _orchestrator(tmp_path: Path) -> MainOrchestrator:
    return MainOrchestrator(repository=DealRepository(tmp_path / "deals.db"))


def _new_deal(orchestrator: MainOrchestrator, deal_id: str):
    return orchestrator.process_incoming_deal(
        deal_id=deal_id,
        contract_path=SAMPLE_DOCX,
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=OUTPUT_DIR,
        max_iterations=3,
    )


def test_deal_repository_persists_state_and_events(tmp_path):
    repository = DealRepository(tmp_path / "deals.db")
    orchestrator = MainOrchestrator(repository=repository)
    state = _new_deal(orchestrator, "PERSIST-1")

    loaded = repository.get("PERSIST-1")
    assert loaded is not None
    assert loaded.deal_id == state.deal_id
    assert loaded.contract_path == str(SAMPLE_DOCX)
    assert loaded.run_status == state.run_status

    listed = repository.list()
    assert any(item["deal_id"] == "PERSIST-1" for item in listed)
    events = repository.events("PERSIST-1")
    assert any(item["event_type"] == "pipeline_completed" for item in events)
    history = repository.history("PERSIST-1")
    assert history and history[-1]["iteration"] == state.iteration


def test_human_reject_starts_next_iteration(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    first = _new_deal(orchestrator, "HITL-REJECT")
    assert first.requires_human_approval is True

    second = orchestrator.decide(
        "HITL-REJECT",
        decision="REJECT",
        reviewer="reviewer@example.com",
        notes="The liability cap and IP ownership must be resolved first.",
    )
    assert second.iteration == 2
    assert second.human_decision == "REJECT"
    assert second.review_feedback is not None
    assert second.run_status in {"AWAITING_HUMAN_REVIEW", "MAX_ITERATIONS_REACHED"}
    assert orchestrator.get_deal("HITL-REJECT").iteration == 2


def test_human_approval_marks_deal_approved(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    _new_deal(orchestrator, "HITL-APPROVE")
    approved = orchestrator.decide(
        "HITL-APPROVE",
        decision="APPROVE",
        reviewer="reviewer@example.com",
        notes="Approved for dispatch.",
    )
    assert approved.run_status == "APPROVED"
    assert approved.is_converged is True
    assert approved.requires_human_approval is False
    assert approved.convergence_reason == "human_approved"


def test_counteroffer_starts_next_iteration(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    _new_deal(orchestrator, "HITL-COUNTER")
    updated = orchestrator.apply_counteroffer(
        "HITL-COUNTER",
        offered_price=110000,
        target_price=100000,
        notes="Vendor moved 10k.",
    )
    assert updated.iteration == 2
    assert updated.offered_price == 110000
    assert updated.counteroffer["offered_price"] == 110000
    assert orchestrator.get_deal("HITL-COUNTER").counteroffer["offered_price"] == 110000


def test_max_iterations_blocks_another_round(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    state = orchestrator.process_incoming_deal(
        deal_id="HITL-MAX",
        contract_path=SAMPLE_DOCX,
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=OUTPUT_DIR,
        max_iterations=1,
    )
    assert state.run_status == "MAX_ITERATIONS_REACHED"
    after = orchestrator.decide("HITL-MAX", "REJECT", notes="No more rounds")
    assert after.run_status == "MAX_ITERATIONS_REACHED"
    assert after.convergence_reason == "max_iterations"


def test_deal_api_endpoints():
    client = TestClient(app)
    app_orchestrator.process_incoming_deal(
        deal_id="API-HITL-1",
        contract_path=SAMPLE_DOCX,
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=OUTPUT_DIR,
    )

    listed = client.get("/api/deals")
    assert listed.status_code == 200
    listed_deal = next(
        item for item in listed.json()["deals"] if item["deal_id"] == "API-HITL-1"
    )
    assert "risk_tier" in listed_deal
    assert "utility" in listed_deal
    assert "requires_human_approval" in listed_deal

    detail = client.get("/api/deals/API-HITL-1")
    assert detail.status_code == 200
    assert detail.json()["deal_id"] == "API-HITL-1"

    events = client.get("/api/deals/API-HITL-1/events")
    assert events.status_code == 200
    assert events.json()["events"]

    history = client.get("/api/deals/API-HITL-1/history")
    assert history.status_code == 200
    assert history.json()["history"]

    decided = client.post(
        "/api/deals/API-HITL-1/decision",
        json={"decision": "APPROVE", "reviewer": "test", "notes": "ok"},
    )
    assert decided.status_code == 200
    assert decided.json()["run_status"] == "APPROVED"

    app_orchestrator.process_incoming_deal(
        deal_id="API-HITL-MANUAL",
        contract_path=SAMPLE_DOCX,
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=OUTPUT_DIR,
    )
    manual = client.post(
        "/api/deals/API-HITL-MANUAL/decision",
        json={
            "decision": "MANUAL_EDIT",
            "reviewer": "test",
            "notes": "Use the revised liability language.",
            "edited_clauses": [{"clause_id": "CL-1", "text": "Revised cap."}],
        },
    )
    assert manual.status_code == 200
    assert manual.json()["iteration"] == 2
    assert manual.json()["manual_edits"]

    app_orchestrator.process_incoming_deal(
        deal_id="API-HITL-COUNTER",
        contract_path=SAMPLE_DOCX,
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=OUTPUT_DIR,
    )
    counter = client.post(
        "/api/deals/API-HITL-COUNTER/counteroffer",
        json={"offered_price": 110000, "target_price": 100000, "notes": "vendor moved"},
    )
    assert counter.status_code == 200
    assert counter.json()["iteration"] == 2
    assert counter.json()["counteroffer"]["offered_price"] == 110000
