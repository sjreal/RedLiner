"""CrewAI tools that call the same MCP servers used by ADK."""

from __future__ import annotations

import json

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from runtime.mcp_client import call_tool


class VendorLookupInput(BaseModel):
    vendor_name: str = Field(description="Vendor company name or domain")


class VendorLookupTool(BaseTool):
    name: str = "vendor_lookup"
    description: str = (
        "Look up vendor risk, sanctions/PEP status and domain age through the "
        "RedLiner vendor MCP server. Use this before relying on vendor risk."
    )
    args_schema: type[BaseModel] = VendorLookupInput

    def _run(self, vendor_name: str) -> str:
        result = call_tool(
            "vendor_tools.py",
            "lookup_vendor",
            {"vendor_name": vendor_name},
        )
        return json.dumps(result, default=str)


class ContractMetadataInput(BaseModel):
    path: str = Field(description="Path to a .docx or .pdf contract under data/")


class ContractMetadataTool(BaseTool):
    name: str = "contract_metadata"
    description: str = (
        "Return safe metadata for a contract file through the RedLiner contract "
        "MCP server."
    )
    args_schema: type[BaseModel] = ContractMetadataInput

    def _run(self, path: str) -> str:
        return json.dumps(
            call_tool("contract_tools.py", "file_metadata", {"path": path}),
            default=str,
        )


class UtilityScoreInput(BaseModel):
    unit_price: float = Field(gt=0, description="Offered unit price")
    target_price: float = Field(gt=0, description="Buyer target price")
    payment_terms_days: int = Field(default=60, ge=0, le=365)
    risk_penalty: float = Field(default=0.0, ge=0.0, le=100.0)


class UtilityScoreTool(BaseTool):
    name: str = "utility_score"
    description: str = (
        "Calculate the normalized buyer utility score through the RedLiner "
        "finance MCP server."
    )
    args_schema: type[BaseModel] = UtilityScoreInput

    def _run(
        self,
        unit_price: float,
        target_price: float,
        payment_terms_days: int = 60,
        risk_penalty: float = 0.0,
    ) -> str:
        return json.dumps(
            call_tool(
                "finance_tools.py",
                "utility_score",
                {
                    "unit_price": unit_price,
                    "target_price": target_price,
                    "payment_terms_days": payment_terms_days,
                    "risk_penalty": risk_penalty,
                },
            ),
            default=str,
        )


class GuardrailCheckInput(BaseModel):
    deal_cost: float = Field(ge=0)
    utility_score: float = Field(ge=0.0, le=1.0)


class GuardrailCheckTool(BaseTool):
    name: str = "guardrail_check"
    description: str = (
        "Check budget and minimum-utility guardrails through the RedLiner "
        "finance MCP server."
    )
    args_schema: type[BaseModel] = GuardrailCheckInput

    def _run(self, deal_cost: float, utility_score: float) -> str:
        return json.dumps(
            call_tool(
                "finance_tools.py",
                "guardrail_check",
                {"deal_cost": deal_cost, "utility_score": utility_score},
            ),
            default=str,
        )


class TradeoffProposalInput(BaseModel):
    offered_price: float = Field(gt=0)
    target_price: float = Field(gt=0)
    vendor_risk_score: float = Field(default=0.0, ge=0.0, le=100.0)


class TradeoffProposalTool(BaseTool):
    name: str = "propose_tradeoff"
    description: str = (
        "Propose a deterministic price/payment-term trade-off through the "
        "RedLiner finance MCP server."
    )
    args_schema: type[BaseModel] = TradeoffProposalInput

    def _run(
        self,
        offered_price: float,
        target_price: float,
        vendor_risk_score: float = 0.0,
    ) -> str:
        return json.dumps(
            call_tool(
                "finance_tools.py",
                "propose_tradeoff",
                {
                    "offered_price": offered_price,
                    "target_price": target_price,
                    "vendor_risk_score": vendor_risk_score,
                },
            ),
            default=str,
        )
