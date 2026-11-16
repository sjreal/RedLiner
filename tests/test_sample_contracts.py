from pathlib import Path

from agents.legal_redliner import LegalRedlinerAgent
from agents.orchestrator import MainOrchestrator
from core.contract_terms import extract_contract_terms
from core.deal_store import DealRepository
from subgraphs.document_parser import DocumentParserSubgraph

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DIR = BASE_DIR / "data" / "sample_contracts"


def _redline(name: str, output_dir: Path):
    source = SAMPLE_DIR / name
    parsed = DocumentParserSubgraph().execute(source)
    return LegalRedlinerAgent().generate_redlined_docx(
        source,
        output_dir / f"{source.stem}_redlined.docx",
        parsed.clauses,
        contract_name=source.stem,
    )


def test_clean_sample_has_no_redlines(tmp_path):
    result = _redline("sample_clean_saas_agreement.docx", tmp_path)
    assert result.actions == []
    assert result.critical_count == 0


def test_unfavorable_sample_triggers_playbook(tmp_path):
    result = _redline("sample_unfavorable_saas_agreement.docx", tmp_path)
    rule_ids = {action.rule_id for action in result.actions}
    assert rule_ids == {
        "RULE_PAY_005",
        "RULE_IP_003",
        "RULE_LIAB_001",
        "RULE_INDEM_002",
        "RULE_TERM_006",
        "RULE_PRIV_007",
        "RULE_LAW_004",
    }
    assert result.critical_count >= 2


def test_medium_risk_sample_triggers_mixed_findings(tmp_path):
    result = _redline("sample_medium_risk_saas_agreement.docx", tmp_path)
    rule_ids = {action.rule_id for action in result.actions}
    assert rule_ids == {"RULE_PAY_005", "RULE_TERM_006", "RULE_PRIV_007"}
    assert result.critical_count == 0


def test_services_sample_triggers_payment_and_law(tmp_path):
    result = _redline("sample_professional_services_agreement.docx", tmp_path)
    rule_ids = {action.rule_id for action in result.actions}
    assert rule_ids == {"RULE_PAY_005", "RULE_LAW_004"}
    assert result.critical_count == 0


def test_dpa_sample_triggers_multiple_critical_findings(tmp_path):
    result = _redline("sample_data_processing_addendum.docx", tmp_path)
    rule_ids = {action.rule_id for action in result.actions}
    assert rule_ids == {
        "RULE_PAY_005",
        "RULE_PRIV_007",
        "RULE_LIAB_001",
        "RULE_INDEM_002",
        "RULE_TERM_006",
        "RULE_LAW_004",
    }
    assert result.critical_count >= 1


def test_priced_sample_computes_utility(tmp_path):
    orchestrator = MainOrchestrator(
        repository=DealRepository(tmp_path / "deals.db")
    )
    state = orchestrator.process_incoming_deal(
        deal_id="UTIL-SAMPLE",
        contract_path=SAMPLE_DIR / "sample_clean_saas_agreement.docx",
        vendor_name="ApexCloud Enterprise Ltd",
        output_dir=tmp_path,
    )
    assert state.offered_price == 120000
    assert state.target_price == 108000
    assert state.normalized_utility_score > 0
    assert state.finance_analysis.get("status") == "complete"


def test_commonpaper_inspired_sample_is_clean_and_priced(tmp_path):
    source = SAMPLE_DIR / "sample_commonpaper_cloud_service_agreement.docx"
    result = _redline(source.name, tmp_path)
    terms = extract_contract_terms(DocumentParserSubgraph().execute(source))
    assert result.actions == []
    assert result.critical_count == 0
    assert terms.offered_price == 150000


def test_acc_cooley_inspired_sample_has_mixed_findings(tmp_path):
    source = SAMPLE_DIR / "sample_acc_cooley_style_saas_agreement.docx"
    result = _redline(source.name, tmp_path)
    terms = extract_contract_terms(DocumentParserSubgraph().execute(source))
    rule_ids = {action.rule_id for action in result.actions}
    assert rule_ids == {
        "RULE_PAY_005",
        "RULE_PRIV_007",
        "RULE_TERM_006",
        "RULE_LAW_004",
    }
    assert terms.offered_price == 240000


def test_pdf_fixture_keeps_price_context():
    parsed = DocumentParserSubgraph().execute(SAMPLE_DIR / "vendor_saas_agreement.pdf")
    terms = extract_contract_terms(parsed)
    assert terms.offered_price == 120000
    assert terms.payment_terms_days == 15
