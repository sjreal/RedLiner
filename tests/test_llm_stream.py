from fastapi.testclient import TestClient

from core.models import OutboundEmailRequest, RedlineResult
from core.state import NegotiationDealState
from server.app import _sse, app, orchestrator as app_orchestrator
from services.opencode_llm import OpenCodeLLM


def _state(deal_id: str) -> NegotiationDealState:
    return NegotiationDealState(
        deal_id=deal_id,
        source_contract_filename="stream_sample.docx",
        run_status="AWAITING_HUMAN_REVIEW",
        redline_result=RedlineResult(
            contract_name="stream_sample",
            total_clauses=2,
            violations_detected=0,
            critical_count=0,
            actions=[],
            output_docx_filename="stream_sample_redlined.docx",
            output_docx_path="data/outputs/stream_sample_redlined.docx",
            summary="Test fixture",
        ),
        counter_proposal_email=OutboundEmailRequest(
            recipient_email="vendor@example.com",
            recipient_name="Vendor Counsel",
            vendor_company="Example Vendor",
            subject="Counter-proposal",
            counter_proposal_body="Template body",
            redlined_docx_filename="stream_sample_redlined.docx",
            deal_id=deal_id,
        ),
    )


def test_sse_format():
    assert _sse("token", {"text": "hello"}) == (
        'event: token\ndata: {"text": "hello"}\n\n'
    )


def test_stream_endpoint_emits_tokens_and_saves_draft(monkeypatch):
    deal_id = "STREAM-TEST"
    app_orchestrator.repository.save(_state(deal_id))

    def fake_stream(self, **kwargs):
        yield "Hello "
        yield "vendor"
        self.last_usage = {"output_tokens": 2}

    monkeypatch.setattr(
        OpenCodeLLM,
        "stream_counter_proposal",
        fake_stream,
    )

    response = TestClient(app).post(
        "/api/email/draft-stream",
        json={"deal_id": deal_id, "instructions": "Be concise."},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: status" in response.text
    assert "event: token" in response.text
    assert "Hello " in response.text
    assert "event: done" in response.text

    updated = app_orchestrator.get_deal(deal_id)
    assert updated is not None
    assert updated.counter_proposal_email is not None
    assert updated.counter_proposal_email.counter_proposal_body == "Hello vendor"


def test_sample_contract_download_endpoint():
    response = TestClient(app).get(
        "/api/samples/sample_clean_saas_agreement.docx"
    )
    assert response.status_code == 200
    assert response.content[:2] == b"PK"


def test_stream_endpoint_rejects_unknown_deal():
    response = TestClient(app).post(
        "/api/email/draft-stream",
        json={"deal_id": "DOES-NOT-EXIST"},
    )
    assert response.status_code == 404
