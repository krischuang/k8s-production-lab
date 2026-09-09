import os

os.environ["READINESS_DELAY_SECONDS"] = "0"

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness_ok():
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


def test_readiness_ok():
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_list_items():
    resp = client.get("/api/items")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    assert len(body["items"]) == 3
    assert body["items"][0]["name"] == "widget"


def test_readiness_fails_when_flagged(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "FAIL_READINESS", True)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
