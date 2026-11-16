"""Print which RedLiner services are enabled and whether they are configured.

Never prints secret values. Exit code 1 when an enabled service is missing
required configuration, so it can be used as a pre-flight check.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "data" / "email_config.json"

load_dotenv(BASE_DIR / ".env", override=False)


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _value(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _email_config() -> Dict[str, object]:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {
        "provider": os.environ.get("EMAIL_PROVIDER", "sandbox").lower(),
        "smtp_user": _value("SMTP_USER"),
        "smtp_password": _value("SMTP_PASSWORD"),
        "from_email": _value("SMTP_FROM"),
    }


def _network_check(url: str, token: str = "") -> Tuple[bool, str]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return True, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # network failures are expected in local demos
        return False, f"{type(exc).__name__}"



def _postgres_check(dsn: str) -> Tuple[bool, str]:
    try:
        from psycopg import connect

        with connect(dsn, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        return True, "SELECT 1 ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"


def build_rows(network: bool) -> List[Tuple[str, str, str, str]]:
    rows: List[Tuple[str, str, str, str]] = []

    # Model
    model_key = bool(_value("OPENCODE_API_KEY"))
    rows.append(
        (
            "Model",
            "on" if model_key else "off",
            "ready" if model_key else "off (no OPENCODE_API_KEY; deterministic fallback)",
            _value("OPENCODE_MODEL", "glm-5.3-flash"),
        )
    )

    # Email
    email = _email_config()
    provider = str(email.get("provider", "sandbox")).lower()
    smtp_ready = bool(email.get("smtp_user") and email.get("smtp_password"))
    if provider == "smtp":
        email_state = "ready" if smtp_ready else "missing SMTP user/password"
    elif provider == "resend":
        email_state = "ready" if email.get("resend_api_key") else "missing Resend key"
    else:
        email_state = "sandbox (no real delivery)"
    rows.append(("Email", provider, email_state, str(email.get("from_email", ""))))

    # Database
    database_url = _value("DATABASE_URL")
    if database_url:
        if network:
            ok, detail = _postgres_check(database_url)
            state = "ready (connected)" if ok else "unreachable"
            detail = "DATABASE_URL connected" if ok else detail
        else:
            state = "ready (not probed)"
            detail = "DATABASE_URL is set"
        rows.append(("Database", "postgres", state, detail))
    else:
        path = _value("REDLINER_DB_PATH", "data/redliner_deals.db")
        rows.append(("Database", "sqlite", "ready", path))

    # MCP
    mcp_on = _flag("MCP_ENABLED", "true")
    servers = sorted((BASE_DIR / "mcp_servers").glob("*.py"))
    server_files = [p for p in servers if p.name != "__init__.py"]
    mcp_state = "ready" if mcp_on and len(server_files) == 3 else "missing server files"
    rows.append(
        (
            "MCP",
            "on" if mcp_on else "off",
            mcp_state if mcp_on else "disabled",
            f"{len(server_files)} stdio servers",
        )
    )

    # Live OSINT
    osint_on = _flag("LIVE_OSINT_ENABLED", "true")
    optional_search = bool(_value("TAVILY_API_KEY") or _value("SERPER_API_KEY"))
    rows.append(
        (
            "Live OSINT",
            "on" if osint_on else "off",
            "ready (GLEIF + DuckDuckGo fallback)"
            if osint_on
            else "disabled",
            "optional Tavily/Serper set" if optional_search else "no optional search key",
        )
    )

    # Guardrails
    guard_on = _flag("LLM_GUARDRAILS_ENABLED", "true")
    rows.append(
        (
            "Guardrails",
            "on" if guard_on else "off",
            "ready" if guard_on else "disabled",
            "deterministic checks",
        )
    )

    # Langfuse
    langfuse_flag = _flag("LANGFUSE_TRACING_ENABLED", "true")
    public_key = bool(_value("LANGFUSE_PUBLIC_KEY"))
    secret_key = bool(_value("LANGFUSE_SECRET_KEY"))
    if not langfuse_flag:
        langfuse_state = "disabled"
    elif public_key and secret_key:
        langfuse_state = "ready"
    elif public_key or secret_key:
        langfuse_state = "missing one Langfuse key"
    else:
        langfuse_state = "off (no keys)"
    rows.append(
        (
            "Langfuse",
            "on" if langfuse_flag and public_key and secret_key else "off",
            langfuse_state,
            _value("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    )

    # A2A
    a2a_on = _flag("A2A_ENABLED")
    a2a_url = _value("A2A_VENDOR_URL", "http://127.0.0.1:8001")
    a2a_token = _value("A2A_SERVICE_TOKEN")
    if not a2a_on:
        a2a_state = "disabled"
    elif not a2a_token:
        a2a_state = "warning: no A2A_SERVICE_TOKEN"
    elif network:
        ok, detail = _network_check(
            f"{a2a_url.rstrip('/')}/.well-known/agent-card.json", a2a_token
        )
        a2a_state = f"ready ({detail})" if ok else f"unreachable ({detail})"
    else:
        a2a_state = "ready (not probed)"
    rows.append(("A2A", "on" if a2a_on else "off", a2a_state, a2a_url))

    # Gmail poller
    gmail_on = _flag("GMAIL_POLL_ENABLED")
    gmail_ready = bool(email.get("smtp_user") and email.get("smtp_password"))
    rows.append(
        (
            "Gmail poller",
            "on" if gmail_on else "off",
            (
                "ready"
                if gmail_on and gmail_ready
                else (
                    "missing Gmail user/password in email config"
                    if gmail_on
                    else "disabled"
                )
            ),
            f"label {_value('GMAIL_POLL_FOLDER', 'RedLiner')}",
        )
    )

    # Demo auth
    auth_on = bool(_value("DEMO_PASSWORD"))
    rows.append(
        (
            "Demo auth",
            "on" if auth_on else "off",
            "ready" if auth_on else "disabled (no DEMO_PASSWORD)",
            f"user {_value('DEMO_USER', 'demo')}",
        )
    )

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--network",
        action="store_true",
        help="Probe the A2A agent card and Postgres connection.",
    )
    args = parser.parse_args()

    rows = build_rows(args.network)
    headers = ("Service", "Enabled", "State", "Detail")
    widths = [
        max(len(headers[i]), max(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]

    def line(values: Tuple[str, ...]) -> str:
        return "  ".join(value.ljust(widths[i]) for i, value in enumerate(values))

    print(line(headers))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print(line(row))

    failures = [row for row in rows if row[2].startswith(("missing", "unreachable"))]
    if failures:
        print()
        for service, _, state, _ in failures:
            print(f"ACTION: {service}: {state}")
        return 1

    print()
    print("All enabled services are configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
