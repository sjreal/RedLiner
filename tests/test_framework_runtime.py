import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agents.orchestrator import MainOrchestrator
from runtime.adk_runtime import AdkPipeline
from runtime.crew_runtime import CrewAIRuntime
from runtime.llm import build_adk_model, build_crewai_llm
from server.app import app

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DOCX = BASE_DIR / "data" / "sample_contracts" / "vendor_saas_agreement.docx"
OUTPUT_DIR = BASE_DIR / "data" / "outputs"


def test_adk_pipeline_runs_without_langgraph():
    result = AdkPipeline().run(
        deal_id="FRAMEWORK-ADK-TEST",
        contract_path=SAMPLE_DOCX,
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=OUTPUT_DIR,
    )
    assert result["adk_event_count"] > 0
    assert len(result["parsed_clauses"]) >= 7
    assert len(result["redline_actions"]) >= 5
    assert result["vendor_profile"]["risk_tier"] == "LOW"
    assert result["requires_human_approval"] is True
    assert result["commercial_rounds"] == 2


def test_orchestrator_exposes_both_frameworks():
    orchestrator = MainOrchestrator()
    state = orchestrator.process_incoming_deal(
        deal_id="FRAMEWORK-ORCH-TEST",
        contract_path=SAMPLE_DOCX,
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=OUTPUT_DIR,
    )
    assert state.runtime_frameworks == ["CrewAI", "Google ADK"]
    assert state.adk_event_count > 0
    assert state.pipeline_error is None
    assert state.counter_proposal_email is not None


def test_crewai_disables_cleanly_without_a_key():
    runtime = CrewAIRuntime()
    assert runtime.enabled is False
    result = runtime.run(
        contract_name="sample",
        vendor_name="Vendor",
        risk_score=10.0,
        redline_actions=[],
        offered_price=None,
        target_price=None,
        finance_analysis={},
        tradeoff_proposal={},
        recipient_email="legal@example.com",
        recipient_name="Vendor Counsel",
    )
    assert result.status == "disabled"


def test_health_reports_framework_runtime():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["frameworks"] == ["CrewAI", "Google ADK"]
    assert payload["runtime"] == "CrewAI + Google ADK"


def test_native_framework_model_adapters():
    with patch.dict(os.environ, {"OPENCODE_API_KEY": "test-key"}):
        crew_llm = build_crewai_llm()
        adk_model = build_adk_model()
    assert crew_llm is not None
    assert adk_model is not None
    assert type(crew_llm).__module__.startswith("crewai")
    assert type(adk_model).__module__.startswith("google.adk")
