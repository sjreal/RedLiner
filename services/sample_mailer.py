"""Send bundled sample contracts through the configured SMTP account."""

from __future__ import annotations

import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.email_connector import EmailConnectorService
from core.sender import sender_identity

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DIR = BASE_DIR / "data" / "sample_contracts"
DEFAULT_SAMPLE = "sample_clean_saas_agreement.docx"


def list_samples() -> List[str]:
    return sorted(
        path.name
        for path in SAMPLE_DIR.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".docx", ".pdf"}
        and "_redlined" not in path.stem
    )


def resolve_sample(name: str) -> Path:
    safe_name = Path(name).name
    path = SAMPLE_DIR / safe_name
    if not path.exists():
        raise FileNotFoundError(f"Sample contract not found: {safe_name}")
    if path.suffix.lower() not in {".docx", ".pdf"}:
        raise ValueError("Only .docx and .pdf samples can be sent")
    return path


def build_sample_message(
    *,
    config: Dict[str, Any],
    contract: Path,
    recipient: str,
    subject: Optional[str] = None,
    body: Optional[str] = None,
) -> EmailMessage:
    sender = str(config.get("smtp_user") or config.get("from_email") or "").strip()
    display_name, company_name = sender_identity()
    sender_name = str(config.get("from_name") or display_name).strip()
    if not sender:
        raise ValueError("SMTP sender is not configured in data/email_config.json")

    message = EmailMessage()
    message["From"] = formataddr((sender_name, sender))
    message["To"] = recipient
    message["Subject"] = subject or f"[RedLiner] Sample contract: {contract.stem}"
    message["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    message["X-RedLiner-Sample"] = "1"
    message.set_content(
        body
        or (
            "Hello,\n\n"
            f"Attached is the RedLiner test contract '{contract.name}'.\n\n"
            "This message is part of an inbound-email workflow test. If the Gmail "
            "poller is enabled, create a filter that applies the RedLiner label to "
            "messages with this subject, or apply the label manually. The backend "
            "must be running for the poller to process it.\n\n"
            f"Regards,\n{display_name}\n{company_name}\n"
        )
    )

    content_type, _ = mimetypes.guess_type(contract.name)
    maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
    message.add_attachment(
        contract.read_bytes(),
        maintype=maintype,
        subtype=subtype,
        filename=contract.name,
    )
    return message


def _send_smtp(config: Dict[str, Any], message: EmailMessage) -> None:
    provider = str(config.get("provider", "sandbox")).lower()
    if provider != "smtp":
        raise ValueError(
            f"Email provider is '{provider}', not 'smtp'. "
            "Select Direct SMTP in the dashboard or set EMAIL_PROVIDER=smtp."
        )

    host = str(config.get("smtp_host") or "smtp.gmail.com")
    port = int(config.get("smtp_port") or 587)
    user = str(config.get("smtp_user") or "")
    password = str(config.get("smtp_password") or "")
    use_tls = bool(config.get("smtp_use_tls", True))
    if not user or not password:
        raise ValueError("SMTP user/password are missing in data/email_config.json")

    if port == 465:
        with smtplib.SMTP_SSL(
            host, port, timeout=20, context=ssl.create_default_context()
        ) as server:
            server.login(user, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            if use_tls:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            server.login(user, password)
            server.send_message(message)


def send_sample_contract(
    contract: str = DEFAULT_SAMPLE,
    *,
    recipient: Optional[str] = None,
    subject: Optional[str] = None,
    body: Optional[str] = None,
) -> Dict[str, Any]:
    config = EmailConnectorService().get_config(mask_secret=False)
    sender = str(config.get("smtp_user") or config.get("from_email") or "").strip()
    target = (recipient or sender).strip()
    if not target or "@" not in target:
        raise ValueError("No recipient. Configure SMTP_USER or pass a recipient email.")

    path = resolve_sample(contract)
    message = build_sample_message(
        config=config,
        contract=path,
        recipient=target,
        subject=subject,
        body=body,
    )
    _send_smtp(config, message)
    return {
        "status": "SENT",
        "contract": path.name,
        "recipient": target,
        "message_id": message["Message-ID"],
        "provider": str(config.get("provider", "smtp")),
    }
