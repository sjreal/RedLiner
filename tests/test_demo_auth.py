import base64
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.app import app


def _basic(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def test_health_stays_public_and_deals_require_demo_login():
    client = TestClient(app)
    with patch.dict(
        os.environ,
        {"DEMO_USER": "demo", "DEMO_PASSWORD": "demo-pass"},
    ):
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/deals").status_code == 401
        assert (
            client.get(
                "/api/deals",
                headers={"Authorization": _basic("demo", "wrong")},
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/api/deals",
                headers={"Authorization": _basic("demo", "demo-pass")},
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/api/settings",
                headers={"Authorization": _basic("demo", "demo-pass")},
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/deals.html",
                headers={"Authorization": _basic("demo", "demo-pass")},
            ).status_code
            == 200
        )


def test_auth_is_disabled_when_demo_password_is_unset():
    client = TestClient(app)
    with patch.dict(os.environ, {"DEMO_USER": "demo", "DEMO_PASSWORD": ""}):
        assert client.get("/api/deals").status_code == 200
