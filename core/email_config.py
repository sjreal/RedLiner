"""Shared access to the app's existing email configuration."""

from __future__ import annotations

from typing import Dict


def get_email_credentials() -> Dict[str, str]:
    """Return unmasked SMTP/IMAP credentials from the app configuration."""
    from services.email_connector import EmailConnectorService

    config = EmailConnectorService().get_config(mask_secret=False)
    return {
        "smtp_host": str(config.get("smtp_host", "smtp.gmail.com")),
        "smtp_port": str(config.get("smtp_port", 587)),
        "smtp_user": str(config.get("smtp_user", "")),
        "smtp_password": str(config.get("smtp_password", "")),
        "from_email": str(config.get("from_email", "")),
    }
