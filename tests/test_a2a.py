import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from runtime.a2a_tools import A2AVendorTool
from server.app import app

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
                "A2A_ENABLED": "true",
                "A2A_VENDOR_URL": base_url,
                "A2A_TIMEOUT_SECONDS": "20",
                "A2A_SERVICE_TOKEN": "test-a2a-token",
            },
        ):
            result = json.loads(
                A2AVendorTool()._run("ApexCloud Enterprise Ltd")
            )
            status = TestClient(app).get("/api/a2a/status").json()
        assert result["risk_tier"] == "LOW"
        assert result["sanction_pep_status"] == "CLEARED"
        assert status["enabled"] is True
        assert status["reachable"] is True
        assert status["agent_name"] == "vendor_intelligence"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_a2a_status_disabled(monkeypatch):
    monkeypatch.setenv("A2A_ENABLED", "false")
    data = TestClient(app).get("/api/a2a/status").json()
    assert data["enabled"] is False
    assert data["reachable"] is False
    assert data["status"] == "disabled"


def test_a2a_status_unreachable(monkeypatch):
    monkeypatch.setenv("A2A_ENABLED", "true")
    monkeypatch.setenv("A2A_VENDOR_URL", f"http://127.0.0.1:{_free_port()}")
    monkeypatch.setenv("A2A_SERVICE_TOKEN", "test-token")
    monkeypatch.setenv("A2A_TIMEOUT_SECONDS", "2")
    data = TestClient(app).get("/api/a2a/status").json()
    assert data["enabled"] is True
    assert data["reachable"] is False
    assert data["error"]
