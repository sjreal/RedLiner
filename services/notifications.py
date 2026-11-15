"""Reviewer notifications for paused deals."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

import requests

from core.state import NegotiationDealState
from services.email_connector import EmailConnectorService


def approval_token(deal_id: str, ttl_seconds: int = 86400) -> str:
    """Create a signed, expiring convenience token for a review link."""
    secret = os.environ.get("APPROVAL_SECRET", "change-me").encode()
    payload = base64.urlsafe_b64encode(
        json.dumps({"deal_id": deal_id, "exp": int(time.time()) + ttl_seconds}).encode()
    ).decode()
    signature = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{signature}"


class ReviewerNotifier:
    def __init__(self) -> None:
        self.email_service = EmailConnectorService()

    def notify(self, state: NegotiationDealState) -> Dict[str, Any]:
        reviewer = os.environ.get("REVIEWER_EMAIL", "").strip()
        webhook = os.environ.get("REVIEWER_WEBHOOK_URL", "").strip()
        if not reviewer and not webhook:
            return {"status": "skipped", "reason": "REVIEWER_EMAIL/REVIEWER_WEBHOOK_URL unset"}

        base_url = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8000").rstrip("/")
        token = approval_token(state.deal_id)
        link = f"{base_url}/deals.html?deal={state.deal_id}&token={token}"
        subject = f"[RedLiner] Review required: {state.deal_id}"
        risk = state.vendor_profile.risk_tier.value if state.vendor_profile else "UNKNOWN"
        body = (
            f"Deal {state.deal_id} needs human review.\n\n"
            f"Vendor: {state.vendor_profile.company_name if state.vendor_profile else 'Unknown'}\n"
            f"Risk tier: {risk}\n"
            f"Violations: {len(state.redline_actions)}\n"
            f"Iteration: {state.iteration}/{state.max_iterations}\n"
            f"Reason: {state.convergence_reason or state.run_status}\n\n"
            f"Open the review workbench: {link}\n"
        )

        result: Dict[str, Any] = {"status": "sent", "link": link, "deliveries": []}

        if reviewer:
            try:
                result["deliveries"].append(
                    self.email_service.send_notification(
                        recipient_email=reviewer,
                        subject=subject,
                        body_text=body,
                    )
                )
            except Exception as exc:
                result["deliveries"].append(
                    {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
                )

        if webhook:
            try:
                response = requests.post(
                    webhook,
                    json={
                        "deal_id": state.deal_id,
                        "status": state.run_status,
                        "reason": state.convergence_reason,
                        "link": link,
                    },
                    timeout=10,
                )
                result["deliveries"].append(
                    {"status": "webhook", "code": response.status_code}
                )
            except Exception as exc:
                result["deliveries"].append(
                    {"status": "webhook_error", "error": f"{type(exc).__name__}: {exc}"}
                )
        return result
