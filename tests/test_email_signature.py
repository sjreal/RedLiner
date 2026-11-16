from agents.email_writer import EmailWriterAgent
from core.models import RedlineResult


def _redline() -> RedlineResult:
    return RedlineResult(
        contract_name="signature_sample",
        total_clauses=1,
        violations_detected=0,
        critical_count=0,
        actions=[],
        output_docx_filename="signature_sample_redlined.docx",
        output_docx_path="data/outputs/signature_sample_redlined.docx",
        summary="Signature test",
    )


def test_template_email_uses_configured_signature():
    request = EmailWriterAgent().compose_counter_proposal(
        _redline(),
        recipient_email="vendor@example.com",
        recipient_name="Vendor Counsel",
    )
    body = request.counter_proposal_body
    assert "Siddharth Jain" in body
    assert "BML Munjal University" in body
    assert "RedLiner Procurement & Legal Operations Team" not in body


def test_llm_draft_signature_replaces_generic_closing():
    request = EmailWriterAgent().compose_counter_proposal(
        _redline(),
        recipient_email="vendor@example.com",
        recipient_name="Vendor Counsel",
        draft_body=(
            "Dear Counsel,\n\nPlease review the attached redlines.\n\n"
            "Best regards,\nRedLiner Team"
        ),
    )
    body = request.counter_proposal_body
    assert "Siddharth Jain" in body
    assert "BML Munjal University" in body
    assert "RedLiner Team" not in body


def test_signature_can_be_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("REDLINER_SENDER_NAME", "Test Negotiator")
    monkeypatch.setenv("REDLINER_SENDER_COMPANY", "Test University")
    request = EmailWriterAgent().compose_counter_proposal(
        _redline(),
        recipient_email="vendor@example.com",
        recipient_name="Vendor Counsel",
    )
    body = request.counter_proposal_body
    assert "Test Negotiator" in body
    assert "Test University" in body
