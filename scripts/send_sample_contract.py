"""Send a sample contract to the configured mailbox or the local webhook.

The script reads SMTP credentials from data/email_config.json. It never prints
the password. Use --dry-run to inspect the message without sending.

Examples:
    PYTHONPATH=. uv run python scripts/send_sample_contract.py --list
    PYTHONPATH=. uv run python scripts/send_sample_contract.py --dry-run
    PYTHONPATH=. uv run python scripts/send_sample_contract.py \
        --contract sample_unfavorable_saas_agreement.docx
    PYTHONPATH=. uv run python scripts/send_sample_contract.py --local-webhook
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from email.utils import make_msgid
from typing import Any, Dict

import requests

from core.env import load_app_env
from services.email_connector import EmailConnectorService
from services.sample_mailer import (
    DEFAULT_SAMPLE,
    build_sample_message,
    list_samples,
    resolve_sample,
    send_sample_contract,
)

load_app_env()


def _config() -> Dict[str, Any]:
    return EmailConnectorService().get_config(mask_secret=False)


def _default_recipient(config: Dict[str, Any]) -> str:
    return str(config.get("smtp_user") or config.get("from_email") or "").strip()


def _post_local_webhook(
    *,
    webhook_url: str,
    webhook_token: str,
    config: Dict[str, Any],
    contract,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    sender = str(config.get("smtp_user") or config.get("from_email") or "")
    payload = {
        "message_id": make_msgid(domain="redliner.local"),
        "from_email": sender,
        "from_name": "RedLiner Sample Vendor",
        "to_email": recipient,
        "subject": subject,
        "text_content": body,
        "html_content": "",
        "attachments": [
            {
                "filename": contract.name,
                "content_base64": base64.b64encode(contract.read_bytes()).decode("ascii"),
            }
        ],
    }
    headers = {"X-RedLiner-Webhook-Token": webhook_token} if webhook_token else {}
    response = requests.post(webhook_url, json=payload, headers=headers, timeout=120)
    print(f"Webhook HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2)[:4000])
    except ValueError:
        print(response.text[:4000])
    response.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_SAMPLE, help="Sample filename")
    parser.add_argument("--to", default="", help="Recipient; defaults to the SMTP user")
    parser.add_argument("--subject", default="", help="Email subject")
    parser.add_argument("--body", default="", help="Plain-text email body")
    parser.add_argument("--list", action="store_true", help="List available sample contracts")
    parser.add_argument("--dry-run", action="store_true", help="Build the message but do not send")
    parser.add_argument(
        "--local-webhook",
        action="store_true",
        help="POST to the local /api/webhook/email instead of sending SMTP mail",
    )
    parser.add_argument(
        "--webhook-url",
        default="http://127.0.0.1:8000/api/webhook/email",
        help="Local webhook URL",
    )
    args = parser.parse_args()

    if args.list:
        for name in list_samples():
            print(name)
        return 0

    config = _config()
    contract = resolve_sample(args.contract)
    recipient = (args.to or _default_recipient(config)).strip()
    if not recipient or "@" not in recipient:
        raise SystemExit("No recipient. Pass --to you@example.com or configure SMTP_USER.")

    subject = args.subject or f"[RedLiner] Sample contract: {contract.stem}"
    body = args.body or (
        "Hello,\n\n"
        f"Attached is the RedLiner test contract '{contract.name}'.\n\n"
        "This message is part of an inbound-email workflow test. If the Gmail poller "
        "is enabled, create a filter that applies the RedLiner label to messages "
        "with this subject, or apply the label manually. The backend must be running "
        "for the poller to process it.\n\n"
        "Regards,\nRedLiner Test Harness\n"
    )

    if args.local_webhook:
        _post_local_webhook(
            webhook_url=args.webhook_url,
            webhook_token=os.environ.get("REDLINER_WEBHOOK_TOKEN", "").strip(),
            config=config,
            contract=contract,
            recipient=recipient,
            subject=subject,
            body=body,
        )
        return 0

    print(f"Contract: {contract}")
    print(f"Recipient: {recipient}")
    print(f"Subject: {subject}")
    print(f"Attachment: {contract.name} ({contract.stat().st_size} bytes)")

    if args.dry_run:
        build_sample_message(
            config=config,
            contract=contract,
            recipient=recipient,
            subject=subject,
            body=body,
        )
        print("Dry run: message not sent.")
        return 0

    result = send_sample_contract(
        contract.name,
        recipient=recipient,
        subject=subject,
        body=body,
    )
    print("Email sent.")
    print(f"Message-ID: {result['message_id']}")
    print("If Gmail polling is enabled, the message must receive the RedLiner label.")
    print("Start the backend before expecting the poller to process it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
