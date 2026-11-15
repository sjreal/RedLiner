import os
from unittest.mock import patch

from core.state import NegotiationDealState
from services.notifications import ReviewerNotifier, approval_token


def test_reviewer_notification_uses_signed_link():
    state = NegotiationDealState(
        deal_id="NOTIFY-1",
        source_contract_filename="contract.docx",
        run_status="AWAITING_HUMAN_REVIEW",
        convergence_reason="human_approval_required",
    )
    token = approval_token("NOTIFY-1")
    assert token.count(".") == 1

    with (
        patch.dict(
            os.environ,
            {
                "REVIEWER_EMAIL": "reviewer@example.com",
                "REVIEWER_WEBHOOK_URL": "",
                "APPROVAL_SECRET": "test-secret",
                "DASHBOARD_URL": "http://testserver",
            },
        ),
        patch(
            "services.notifications.EmailConnectorService.send_notification",
            return_value={"status": "success"},
        ) as send,
    ):
        result = ReviewerNotifier().notify(state)

    assert result["status"] == "sent"
    assert "deal=NOTIFY-1" in result["link"]
    send.assert_called_once()


def test_notification_is_skipped_without_reviewer():
    state = NegotiationDealState(
        deal_id="NOTIFY-2",
        source_contract_filename="contract.docx",
    )
    with patch.dict(
        os.environ,
        {"REVIEWER_EMAIL": "", "REVIEWER_WEBHOOK_URL": ""},
    ):
        result = ReviewerNotifier().notify(state)
    assert result["status"] == "skipped"
