"""Produce a clean DOCX: accept all tracked changes and drop comments.

The redlined document is the audit artifact. This module creates the "final"
copy a lawyer or vendor would receive: insertions accepted, deletions applied,
comment anchors and comment parts removed.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

COMMENT_REL_TYPES = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments",
    "http://schemas.microsoft.com/office/2011/relationships/commentsExtended",
    "http://schemas.microsoft.com/office/2016/09/relationships/commentsIds",
    "http://schemas.microsoft.com/office/2018/08/relationships/commentsExtensible",
}

# Revision records that only carry change metadata.
_CHANGE_TAGS = (
    "w:rPrChange",
    "w:pPrChange",
    "w:tblPrChange",
    "w:trPrChange",
    "w:tcPrChange",
    "w:sectPrChange",
    "w:numberingChange",
)


def _unwrap(element) -> None:
    """Replace an element with its children, keeping document order."""
    parent = element.getparent()
    if parent is None:
        return
    index = parent.index(element)
    for child in list(element):
        element.remove(child)
        parent.insert(index, child)
        index += 1
    parent.remove(element)


def _remove(element) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _clean_root(root) -> None:
    # Accept deletions by removing them and their delText.
    for tag in ("w:del", "w:moveFrom"):
        for element in list(root.iter(qn(tag))):
            _remove(element)

    # Accept insertions by promoting their runs into the paragraph.
    for tag in ("w:ins", "w:moveTo"):
        for element in list(root.iter(qn(tag))):
            _unwrap(element)

    # Drop comment anchors and the run that holds the reference.
    for tag in ("w:commentRangeStart", "w:commentRangeEnd"):
        for element in list(root.iter(qn(tag))):
            _remove(element)

    for reference in list(root.iter(qn("w:commentReference"))):
        run = reference.getparent()
        if run is not None and run.tag == qn("w:r"):
            _remove(run)
        else:
            _remove(reference)

    for tag in _CHANGE_TAGS:
        for element in list(root.iter(qn(tag))):
            _remove(element)


def _drop_comment_parts(document: Document) -> None:
    for rel_id, relationship in list(document.part.rels.items()):
        if relationship.reltype in COMMENT_REL_TYPES:
            document.part.drop_rel(rel_id)


def finalize_docx(source_path: Path, destination_path: Path) -> Path:
    """Write a clean copy of ``source_path`` with all changes accepted."""
    source_path = Path(source_path)
    destination_path = Path(destination_path)
    document = Document(str(source_path))

    _clean_root(document.element.body)
    for section in document.sections:
        for container in (section.header, section.footer):
            if container is not None:
                _clean_root(container._element)

    _drop_comment_parts(document)

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(destination_path))
    return destination_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path, nargs="?")
    args = parser.parse_args()
    destination = args.destination or args.source.with_name(
        f"{args.source.stem}_final{args.source.suffix}"
    )
    print(finalize_docx(args.source, destination))


if __name__ == "__main__":
    main()
