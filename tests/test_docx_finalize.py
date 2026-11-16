import zipfile
from pathlib import Path

from core.docx_finalize import finalize_docx
from core.models import ActionType, ClauseType, RedlineAction, SeverityLevel
from subgraphs.playbook_matcher.word_modifier import WordModifier

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DOCX = BASE_DIR / "data" / "sample_contracts" / "vendor_saas_agreement.docx"


def _document_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def test_finalize_accepts_changes_and_removes_comments(tmp_path):
    action = RedlineAction(
        action_id="A-1",
        clause_id="C-1",
        clause_type=ClauseType.PAYMENT_TERMS,
        action_type=ActionType.REPLACE,
        target_paragraph_index=3,
        original_text="Vendor grants Customer a non-exclusive, non-transferable subscription right",
        replacement_text="Vendor grants Customer a worldwide, non-exclusive subscription right",
        comment="Test guardrail rationale.",
        rule_id="RULE_PAY_005",
        rule_name="Net 60 Payment Terms",
        severity=SeverityLevel.HIGH,
    )

    redlined = tmp_path / "redlined.docx"
    WordModifier().modify_docx(SAMPLE_DOCX, redlined, [action])

    redlined_xml = _document_xml(redlined)
    assert "<w:ins " in redlined_xml
    assert "<w:del " in redlined_xml
    assert "Test guardrail rationale." in zipfile.ZipFile(redlined).read("word/comments.xml").decode()

    final = tmp_path / "final.docx"
    finalize_docx(redlined, final)

    final_xml = _document_xml(final)
    assert "<w:ins " not in final_xml
    assert "<w:del " not in final_xml
    assert "<w:commentRangeStart" not in final_xml
    assert "<w:commentReference" not in final_xml
    assert "worldwide, non-exclusive subscription right" in final_xml
    assert "non-exclusive, non-transferable subscription right" not in final_xml

    with zipfile.ZipFile(final) as archive:
        names = set(archive.namelist())
    assert "word/comments.xml" not in names


def test_finalize_is_idempotent(tmp_path):
    redlined = tmp_path / "redlined.docx"
    WordModifier().modify_docx(SAMPLE_DOCX, redlined, [])
    first = tmp_path / "first.docx"
    second = tmp_path / "second.docx"
    finalize_docx(redlined, first)
    finalize_docx(first, second)
    assert _document_xml(first) == _document_xml(second)
