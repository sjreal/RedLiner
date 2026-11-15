"""MCP server for vendor intelligence and sanctions checks."""

from __future__ import annotations

import re

from mcp.server.fastmcp import FastMCP

from subgraphs.vendor_information import VendorInformationSubgraph

mcp = FastMCP(
    "redliner-vendor-tools",
    instructions="Look up vendor risk, sanctions/PEP status and domain age.",
)

_DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _vendor(name: str):
    clean = (name or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError("A vendor name or domain is required (max 200 characters)")
    return VendorInformationSubgraph().assess_vendor(clean)


@mcp.tool()
def lookup_vendor(vendor_name: str) -> dict:
    """Return the vendor risk profile, including tier, score, flags and sources."""
    return _vendor(vendor_name).model_dump(mode="json")


@mcp.tool()
def sanctions_screen(vendor_name: str) -> dict:
    """Return sanctions/PEP status and the risk tier for a vendor."""
    profile = _vendor(vendor_name)
    return {
        "vendor_name": profile.company_name,
        "sanction_pep_status": profile.sanction_pep_status.value,
        "risk_score": profile.risk_score,
        "risk_tier": profile.risk_tier.value,
        "flags": profile.flags,
    }


@mcp.tool()
def domain_age(domain: str) -> dict:
    """Return the observed/indicative domain age for a vendor domain."""
    clean = (domain or "").strip().lower()
    if not _DOMAIN_RE.fullmatch(clean):
        raise ValueError("Provide a domain such as example.com")
    profile = _vendor(clean)
    return {
        "domain": clean,
        "domain_age_years": profile.domain_age_years,
        "risk_score": profile.risk_score,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
