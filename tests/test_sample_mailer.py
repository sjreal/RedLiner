import sys

from fastapi.testclient import TestClient

from server.app import app

server_module = sys.modules["server.app"]


def test_sample_list_includes_fixtures():
    response = TestClient(app).get("/api/email/samples")
    assert response.status_code == 200
    samples = response.json()["samples"]
    assert "sample_clean_saas_agreement.docx" in samples
    assert "sample_unfavorable_saas_agreement.docx" in samples


def test_send_sample_endpoint(monkeypatch):
    calls = {}

    def fake_send(contract, recipient=None):
        calls["contract"] = contract
        calls["recipient"] = recipient
        return {
            "status": "SENT",
            "contract": contract,
            "recipient": recipient or "test@example.com",
        }

    monkeypatch.setattr(server_module, "send_sample_contract", fake_send)

    response = TestClient(app).post(
        "/api/email/send-sample",
        json={
            "contract": "sample_clean_saas_agreement.docx",
            "to": "me@example.com",
        },
    )

    assert response.status_code == 200
    assert calls == {
        "contract": "sample_clean_saas_agreement.docx",
        "recipient": "me@example.com",
    }
    assert response.json()["status"] == "SENT"


def test_send_sample_missing_fixture_is_404():
    response = TestClient(app).post(
        "/api/email/send-sample",
        json={"contract": "does-not-exist.docx"},
    )
    assert response.status_code == 404
