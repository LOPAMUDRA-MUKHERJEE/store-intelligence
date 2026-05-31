# PROMPT: "Write pytest tests for anomaly detection in a retail store
# analytics API. Test queue spike, dead zone, and conversion drop anomalies.
# Include edge cases: empty store, zero traffic, severity levels."
# CHANGES MADE: Added real store ID, fixed event timestamps to match
# video date, added severity level assertions, tested suggested_action field.

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.ingestion import create_tables, SessionLocal, EventDB

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    create_tables()
    yield
    db = SessionLocal()
    db.query(EventDB).filter(EventDB.store_id == "ANOM_STORE").delete()
    db.commit()
    db.close()


def make_event(visitor_id, event_type, zone_id=None, queue_depth=None, is_staff=False):
    return {
        "store_id": "ANOM_STORE",
        "camera_id": "CAM_TEST",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": "2026-04-10T10:00:00Z",
        "zone_id": zone_id,
        "dwell_ms": 0,
        "is_staff": is_staff,
        "confidence": 0.9,
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": None,
            "session_seq": 1
        }
    }


def ingest(events):
    response = client.post("/events/ingest", json={"events": events})
    assert response.status_code == 200
    return response.json()


def test_anomalies_empty_store():
    response = client.get("/stores/ANOM_STORE/anomalies")
    assert response.status_code == 200
    data = response.json()
    assert "anomalies" in data
    assert isinstance(data["anomalies"], list)


def test_queue_spike_critical():
    events = [
        make_event(f"VIS_{i}", "BILLING_QUEUE_JOIN",
                   zone_id="BILLING", queue_depth=9)
        for i in range(3)
    ]
    ingest(events)
    response = client.get("/stores/ANOM_STORE/anomalies")
    data = response.json()
    queue_anomalies = [a for a in data["anomalies"]
                       if a["type"] == "BILLING_QUEUE_SPIKE"]
    assert len(queue_anomalies) > 0
    assert queue_anomalies[0]["severity"] == "CRITICAL"
    assert "suggested_action" in queue_anomalies[0]


def test_queue_spike_warn():
    events = [
        make_event(f"VIS_{i}", "BILLING_QUEUE_JOIN",
                   zone_id="BILLING", queue_depth=6)
        for i in range(3)
    ]
    ingest(events)
    response = client.get("/stores/ANOM_STORE/anomalies")
    data = response.json()
    queue_anomalies = [a for a in data["anomalies"]
                       if a["type"] == "BILLING_QUEUE_SPIKE"]
    assert len(queue_anomalies) > 0
    assert queue_anomalies[0]["severity"] == "WARN"


def test_no_queue_spike_low_depth():
    events = [
        make_event(f"VIS_{i}", "BILLING_QUEUE_JOIN",
                   zone_id="BILLING", queue_depth=2)
        for i in range(3)
    ]
    ingest(events)
    response = client.get("/stores/ANOM_STORE/anomalies")
    data = response.json()
    queue_anomalies = [a for a in data["anomalies"]
                       if a["type"] == "BILLING_QUEUE_SPIKE"]
    assert len(queue_anomalies) == 0


def test_anomalies_have_required_fields():
    events = [
        make_event(f"VIS_{i}", "BILLING_QUEUE_JOIN",
                   zone_id="BILLING", queue_depth=9)
        for i in range(3)
    ]
    ingest(events)
    response = client.get("/stores/ANOM_STORE/anomalies")
    data = response.json()
    for anomaly in data["anomalies"]:
        assert "type" in anomaly
        assert "severity" in anomaly
        assert "suggested_action" in anomaly
        assert anomaly["severity"] in ["INFO", "WARN", "CRITICAL"]


def test_anomalies_timestamp_present():
    response = client.get("/stores/ANOM_STORE/anomalies")
    data = response.json()
    assert "timestamp" in data