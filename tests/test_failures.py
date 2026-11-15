from pathlib import Path

import pytest

from agents.orchestrator import MainOrchestrator
from core.deal_store import DealRepository
from subgraphs.document_parser import DocumentParserSubgraph

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DOCX = BASE_DIR / "data" / "sample_contracts" / "vendor_saas_agreement.docx"
OUTPUT_DIR = BASE_DIR / "data" / "outputs"


def test_unsupported_contract_extension_is_rejected(tmp_path):
    bad = tmp_path / "contract.txt"
    bad.write_text("not a contract", encoding="utf-8")
    with pytest.raises(ValueError):
        DocumentParserSubgraph().execute(bad)


def test_invalid_human_decision_is_rejected(tmp_path):
    orchestrator = MainOrchestrator(
        repository=DealRepository(tmp_path / "deals.db")
    )
    orchestrator.process_incoming_deal(
        deal_id="FAILURE-DECISION",
        contract_path=SAMPLE_DOCX,
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=OUTPUT_DIR,
    )
    with pytest.raises(ValueError):
        orchestrator.decide("FAILURE-DECISION", "MAYBE")


def test_missing_deal_is_reported(tmp_path):
    orchestrator = MainOrchestrator(
        repository=DealRepository(tmp_path / "deals.db")
    )
    assert orchestrator.get_deal("DOES-NOT-EXIST") is None
    with pytest.raises(KeyError):
        orchestrator.decide("DOES-NOT-EXIST", "APPROVE")
