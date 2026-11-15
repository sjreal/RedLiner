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
