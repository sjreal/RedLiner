"""MCP server for deterministic utility and budget calculations."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from subgraphs.tradeoff_engine import (
    GuardrailChecker,
    PythonMathEngine,
    TradeoffEngineSubgraph,
)

mcp = FastMCP(
    "redliner-finance-tools",
    instructions="Calculate deal utility, guardrail status and a trade-off proposal.",
)


@mcp.tool()
def utility_score(
    unit_price: float,
    target_price: float,
    payment_terms_days: int = 60,
    risk_penalty: float = 0.0,
) -> dict:
    """Calculate the normalized buyer utility score (0.0–1.0)."""
    if unit_price <= 0 or target_price <= 0:
        raise ValueError("Prices must be positive")
    utility = PythonMathEngine.calculate_utility(
        unit_price=unit_price,
        target_price=target_price,
        payment_terms_days=max(0, min(int(payment_terms_days), 365)),
        risk_penalty=max(0.0, min(float(risk_penalty), 100.0)),
    )
    return {"utility_score": utility}


@mcp.tool()
def guardrail_check(deal_cost: float, utility_score: float) -> dict:
    """Check budget and minimum-utility guardrails."""
    if deal_cost < 0:
        raise ValueError("Deal cost cannot be negative")
    if not 0.0 <= utility_score <= 1.0:
        raise ValueError("Utility score must be between 0 and 1")
    return {
        "within_guardrails": GuardrailChecker().is_within_guardrails(
            deal_cost, utility_score
        )
    }


@mcp.tool()
def propose_tradeoff(
    offered_price: float,
    target_price: float,
    vendor_risk_score: float = 0.0,
) -> dict:
    """Propose a deterministic price/payment-term trade-off."""
    if offered_price <= 0 or target_price <= 0:
        raise ValueError("Prices must be positive")
    return TradeoffEngineSubgraph().execute(
        offered_price=offered_price,
        target_price=target_price,
        vendor_risk_score=max(0.0, min(float(vendor_risk_score), 100.0)),
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
