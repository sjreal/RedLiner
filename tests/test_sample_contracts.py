from pathlib import Path

from agents.legal_redliner import LegalRedlinerAgent
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
