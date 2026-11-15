from typing import Optional, Dict, Any
from pathlib import Path
from core.models import RedlineResult, VendorProfile, OutboundEmailRequest
from services.email_connector import EmailConnectorService
from services.opencode_llm import OpenCodeLLM


class EmailWriterAgent:
    """
    Email Writer Core Agent (Section 5.2.e in PDF Synopsis).
    Combines negotiation decisions, contract context, and justifications
    into professional emails for the vendor counterparty.
    """

    def __init__(self, worker_url: Optional[str] = None, llm: Optional[OpenCodeLLM] = None):
        self.service = EmailConnectorService(worker_url)
        self.llm = llm or OpenCodeLLM()
        self.last_llm_error: Optional[str] = None

    def compose_counter_proposal(
        self,
        redline_result: RedlineResult,
        vendor: Optional[VendorProfile] = None,
        recipient_email: str = "vendor-legal@counterparty.com",
        recipient_name: str = "Vendor Legal Counsel",
        draft_body: Optional[str] = None,
        draft_subject: Optional[str] = None,
        deal_id: Optional[str] = None,
    ) -> OutboundEmailRequest:
        request = self.service.generate_counter_proposal_email(
            redline_result=redline_result,
            vendor=vendor,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            deal_id=deal_id,
        )
        self.last_llm_error = None
        if draft_body:
            request.counter_proposal_body = draft_body
            if draft_subject:
                request.subject = draft_subject
            self.llm.status = "crewai"
            return request
        if not self.llm.enabled:
            self.llm.status = "disabled_fallback_template"
            return request

        try:
            action_summary = [
                {
                    "clause_type": action.clause_type.value,
                    "rule_name": action.rule_name,
                    "severity": action.severity.value,
                    "requested_change": action.replacement_text[:500],
                }
                for action in redline_result.actions
            ]
            request.counter_proposal_body = self.llm.draft_counter_proposal(
                vendor_name=request.vendor_company,
                recipient_name=recipient_name,
                contract_name=redline_result.contract_name,
                output_filename=redline_result.output_docx_filename,
                actions=action_summary,
            )
        except Exception as exc:
            # Keep the deterministic, already validated template as a safe fallback.
            self.last_llm_error = type(exc).__name__
        return request

    def dispatch_email(
        self,
        request: OutboundEmailRequest,
        redlined_docx_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        return self.service.dispatch_email(request, redlined_docx_path)
