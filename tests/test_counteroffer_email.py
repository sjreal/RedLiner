from pathlib import Path

from agents.orchestrator import MainOrchestrator
from core.counteroffer import extract_counteroffer
from core.deal_store import DealRepository

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DOCX = BASE_DIR / "data" / "sample_contracts" / "vendor_saas_agreement.docx"
OUTPUT_DIR = BASE_DIR / "data" / "outputs"


def test_counteroffer_extracts_price_terms_and_cap():
    result = extract_counteroffer(
        "We can move to $115,000 with Net 45 and a liability cap of 24 months of fees.",
        target_price=100000,
    )
    assert result.offered_price == 115000
    assert result.payment_terms_days == 45
    assert result.liability_cap == 2400000
    assert result.confidence >= 0.7
    assert result.evidence


def test_ambiguous_reply_does_not_invent_a_price():
    result = extract_counteroffer("We can be flexible on price and terms.")
    assert result.offered_price is None
    assert result.confidence < 0.7


def test_outbound_message_identity_matches_a_reply(tmp_path):
    orchestrator = MainOrchestrator(
        repository=DealRepository(tmp_path / "deals.db")
    )
    state = orchestrator.process_incoming_deal(
        deal_id="EMAIL-THREAD-1",
        contract_path=SAMPLE_DOCX,
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=OUTPUT_DIR,
    )
    email = state.counter_proposal_email
    assert email is not None
    assert email.deal_id == "EMAIL-THREAD-1"
    assert email.message_id
    assert email.headers["X-RedLiner-Deal"] == "EMAIL-THREAD-1"

    orchestrator.record_outbound(email, {"provider": "test", "provider_message_id": "p1"})
    assert orchestrator.find_deal_for_reply(in_reply_to=email.message_id) == "EMAIL-THREAD-1"
    assert (
        orchestrator.find_deal_for_reply(
            deal_reference=email.headers["X-RedLiner-Deal"]
        )
        == "EMAIL-THREAD-1"
    )

    updated = orchestrator.handle_vendor_reply(
        "EMAIL-THREAD-1",
        "We can move to $110,000 with Net 45.",
        subject="Re: Redline & Counter-Proposal",
    )
    assert updated.iteration == 2
    assert updated.offered_price == 110000
    assert updated.counteroffer["status"] == "APPLIED"


def test_low_confidence_reply_requests_review(tmp_path):
    orchestrator = MainOrchestrator(
        repository=DealRepository(tmp_path / "deals.db")
    )
    orchestrator.process_incoming_deal(
        deal_id="EMAIL-THREAD-LOW",
        contract_path=SAMPLE_DOCX,
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=OUTPUT_DIR,
    )
    updated = orchestrator.handle_vendor_reply(
        "EMAIL-THREAD-LOW",
        "We can be flexible on price and terms.",
        subject="Re: terms",
    )
    assert updated.requires_human_approval is True
    assert updated.run_status == "AWAITING_HUMAN_REVIEW"
    assert updated.counteroffer["status"] == "NEEDS_HUMAN_REVIEW"
