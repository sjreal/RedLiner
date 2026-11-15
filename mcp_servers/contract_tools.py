"""MCP server for contract parsing and clause segmentation."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from subgraphs.document_parser import DocumentParserSubgraph

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALLOWED_ROOTS = (PROJECT_ROOT / "data",)
MAX_FILE_BYTES = 25 * 1024 * 1024

mcp = FastMCP(
    "redliner-contract-tools",
    instructions="Parse .docx and .pdf contracts under the RedLiner data directory.",
)


def _safe_contract_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not any(path == root.resolve() or root.resolve() in path.parents for root in ALLOWED_ROOTS):
        raise ValueError("Contract path is outside the RedLiner data directory")
    if path.suffix.lower() not in {".docx", ".pdf"}:
        raise ValueError("Only .docx and .pdf contracts are supported")
    if not path.is_file():
        raise FileNotFoundError(f"Contract not found: {path.name}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Contract exceeds the 25 MiB limit")
    return path


@mcp.tool()
def parse_contract(path: str) -> dict:
    """Parse a contract and return its indexed, typed clauses."""
    parsed = DocumentParserSubgraph().execute(_safe_contract_path(path))
    return parsed.model_dump(mode="json")


@mcp.tool()
def file_metadata(path: str) -> dict:
    """Return safe metadata for a contract file without exposing arbitrary paths."""
    safe_path = _safe_contract_path(path)
    return {
        "filename": safe_path.name,
        "suffix": safe_path.suffix.lower(),
        "size_bytes": safe_path.stat().st_size,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
