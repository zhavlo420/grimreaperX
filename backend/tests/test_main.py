from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def event(**overrides):
    payload = {
        "id": str(uuid4()),
        "device_id": "device-1",
        "app_name": "Code",
        "category": "development",
        "start_ts": "2026-09-30T10:00:00Z",
        "end_ts": "2026-09-30T10:10:00Z",
    }
    payload.update(overrides)
    return payload


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_accepts_valid_usage_event():
    payload = event()
    response = client.post("/v1/usage-events", json=payload)

    assert response.status_code == 202
    assert response.json() == {
        "accepted": True,
        "event_id": payload["id"],
    }


def test_rejects_missing_required_field():
    payload = event()
    del payload["device_id"]

    response = client.post("/v1/usage-events", json=payload)

    assert response.status_code == 422


def test_rejects_blank_device_id():
    response = client.post("/v1/usage-events", json=event(device_id=""))

    assert response.status_code == 422


def test_rejects_invalid_event_id():
    response = client.post("/v1/usage-events", json=event(id="not-a-uuid"))

    assert response.status_code == 422


def test_rejects_invalid_timestamp():
    response = client.post(
        "/v1/usage-events",
        json=event(start_ts="not-a-timestamp"),
    )

    assert response.status_code == 422
