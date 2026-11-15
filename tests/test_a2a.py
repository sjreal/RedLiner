import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import httpx

from runtime.a2a_tools import A2AVendorTool

BASE_DIR = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a2a_server_card_and_crewai_client():
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(BASE_DIR),
        "A2A_PORT": str(port),
        "A2A_SERVICE_TOKEN": "test-a2a-token",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "a2a_servers.vendor_agent:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=BASE_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                card = httpx.get(
                    f"{base_url}/.well-known/agent-card.json",
                    headers={"Authorization": "Bearer test-a2a-token"},
                    timeout=1,
                ).json()
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise AssertionError("A2A server did not become ready")

        assert card["name"] == "vendor_intelligence"
        with patch.dict(
            os.environ,
            {
                "A2A_VENDOR_URL": base_url,
                "A2A_TIMEOUT_SECONDS": "20",
                "A2A_SERVICE_TOKEN": "test-a2a-token",
            },
        ):
            result = json.loads(
                A2AVendorTool()._run("ApexCloud Enterprise Ltd")
            )
        assert result["risk_tier"] == "LOW"
        assert result["sanction_pep_status"] == "CLEARED"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
