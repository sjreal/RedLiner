"""Keep the test suite deterministic and free of live model/email calls."""

import os
import tempfile
from pathlib import Path

import pytest

# The application loads .env, but load_dotenv(override=False) respects this
# pre-set empty value. LLM behavior itself is covered with a mocked response
# in test_milestone_components.py.
os.environ["OPENCODE_API_KEY"] = ""
# Dedicated MCP tests opt back in; the rest of the suite uses the deterministic
# fallback so it stays fast and does not spawn subprocesses.
os.environ["MCP_ENABLED"] = "false"
os.environ["LIVE_OSINT_ENABLED"] = "false"
# Keep local .env demo credentials from turning Basic Auth on for API tests.
os.environ["DEMO_USER"] = "demo"
os.environ["DEMO_PASSWORD"] = ""
os.environ["REDLINER_DB_PATH"] = str(
    Path(tempfile.mkdtemp(prefix="redliner-tests-")) / "deals.db"
)


@pytest.fixture(autouse=True)
def sandbox_email_provider(monkeypatch):
    """Never send SMTP/Worker mail just because tests imported the app."""
    from services.email_connector import EmailConnectorService

    def sandbox_config(self, mask_secret: bool = True):
        return {
            "provider": "sandbox",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_user": "",
            "smtp_password": "",
            "smtp_use_tls": True,
            "from_email": "test@example.com",
            "from_name": "RedLiner Test",
            "resend_api_key": "",
            "has_smtp_password": False,
            "has_resend_api_key": False,
        }

    monkeypatch.setattr(EmailConnectorService, "get_config", sandbox_config)
