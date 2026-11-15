from pathlib import Path

from fastapi.testclient import TestClient

from agents.orchestrator import MainOrchestrator
from core.contract_terms import extract_contract_terms
from core.deal_store import DealRepository
from core.models import Clause, ClauseType, ParsedDocument
from core.report import build_deal_report, report_to_markdown
from server.app import app, orchestrator as app_orchestrator

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DOCX = BASE_DIR / "data" / "sample_contracts" / "vendor_saas_agreement.docx"
OUTPUT_DIR = BASE_DIR / "data" / "outputs"


def test_contract_terms_extraction_from_clauses():
    parsed = ParsedDocument(
        filename="terms.docx",
        file_type="docx",
        total_paragraphs=3,
        clauses=[
            Clause(
                id="1",
                clause_type=ClauseType.PAYMENT_TERMS,
                heading="Payment",
                text="The annual fee is $120,000, payable Net 45.",
                paragraph_index=0,
            ),
            Clause(
                id="2",
                clause_type=ClauseType.LIABILITY_CAP,
                heading="Liability",
                text="Liability is capped at 12 months of fees.",
                paragraph_index=1,
            ),
            Clause(
                id="3",
                clause_type=ClauseType.TERMINATION,
                heading="Term",
                text="The initial term is thirty-six (36) months.",
                paragraph_index=2,
            ),
        ],
        clause_distribution={},
    )
    terms = extract_contract_terms(parsed)
    assert terms.offered_price == 120000
    assert terms.payment_terms_days == 45
    assert terms.liability_cap_basis == "12 months of fees"
    assert terms.initial_term_months == 36
    assert terms.confidence > 0.5


def test_report_contains_structured_sections(tmp_path):
    orchestrator = MainOrchestrator(
        repository=DealRepository(tmp_path / "deals.db")
    )
    state = orchestrator.process_incoming_deal(
        deal_id="REPORT-1",
        contract_path=SAMPLE_DOCX,
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=OUTPUT_DIR,
    )
    report = build_deal_report(
        state,
        events=orchestrator.repository.events("REPORT-1"),
        history=orchestrator.repository.history("REPORT-1"),
    )
    assert report.deal_id == "REPORT-1"
    assert report.vendor is not None
    assert report.redlines
    assert report.history
    assert report.contract_terms.get("payment_terms_days") == 15
    assert report.contract_terms.get("initial_term_months") == 36
    assert report.runtime_frameworks
    markdown = report_to_markdown(report)
    assert "RedLiner Deal Report" in markdown
    assert "## Redlines" in markdown
    assert "## Cost / usage" in markdown


def test_report_api_json_and_markdown():
    client = TestClient(app)
    state = app_orchestrator.process_incoming_deal(
        deal_id="REPORT-API-1",
        contract_path=SAMPLE_DOCX,
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=OUTPUT_DIR,
    )
    json_response = client.get("/api/deals/REPORT-API-1/report")
    assert json_response.status_code == 200
    assert json_response.json()["deal_id"] == "REPORT-API-1"
    assert json_response.json()["redlines"]

    markdown_response = client.get("/api/deals/REPORT-API-1/report?format=markdown")
    assert markdown_response.status_code == 200
    assert "text/markdown" in markdown_response.headers["content-type"]
    assert "RedLiner Deal Report" in markdown_response.text

    assert state.redline_result is not None
    download = client.get(
        f"/api/redliner/download/{state.redline_result.output_docx_filename}"
    )
    assert download.status_code == 200
    assert download.content[:2] == b"PK"
