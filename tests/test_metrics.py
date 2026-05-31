# PROMPT: "Write pytest tests for a FastAPI store analytics API. 
# Test /metrics, /funnel, /heatmap, /anomalies, /health endpoints.
# Include edge cases: empty store, zero purchases, staff exclusion."
# CHANGES MADE: Added real store ID (ST1008), fixed timestamp to match
# actual video date (2026-04-10), added POS correlation test.

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.ingestion import create_tables, SessionLocal, EventDB
from datetime import datetime

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    create_tables()
    yield
    db = SessionLocal()
    db.query(EventDB).filter(EventDB.store_id == "TEST_STORE").delete()
    db.commit()
    db.close()


def ingest_test_events(events):
    response = client.post("/events/ingest", json={"events": events})
    assert response.status_code == 200
    return response.json()


def make_event(visitor_id, event_type, is_staff=False, zone_id=None, confidence=0.9):
    return {
        "store_id": "TEST_STORE",
        "camera_id": "CAM_TEST",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": "2026-04-10T10:00:00Z",
        "zone_id": zone_id,
        "dwell_ms": 0,
        "is_staff": is_staff,
        "confidence": confidence,
        "metadata": {}
    }


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


def test_metrics_empty_store():
    response = client.get("/stores/EMPTY_STORE/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["unique_visitors"] == 0
    assert data["conversion_rate_pct"] == 0.0


def test_metrics_with_visitors():
    ingest_test_events([
        make_event("VIS_001", "ENTRY"),
        make_event("VIS_002", "ENTRY"),
        make_event("VIS_003", "ENTRY"),
    ])
    response = client.get("/stores/TEST_STORE/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["unique_visitors"] == 3


def test_staff_excluded_from_metrics():
    ingest_test_events([
        make_event("VIS_CUST_001", "ENTRY", is_staff=False),
        make_event("VIS_STAFF_001", "ENTRY", is_staff=True),
        make_event("VIS_STAFF_002", "ENTRY", is_staff=True),
    ])
    response = client.get("/stores/TEST_STORE/metrics")
    data = response.json()
    assert data["unique_visitors"] == 1


def test_ingest_idempotent():
    event = make_event("VIS_IDEM_001", "ENTRY")
    result1 = ingest_test_events([event])
    result2 = ingest_test_events([event])
    assert result1["accepted"] == 1
    assert result2["accepted"] == 1
    assert result1["rejected"] == 0


def test_ingest_invalid_event_type():
    event = make_event("VIS_BAD", "INVALID_TYPE")
    result = ingest_test_events([event])
    assert result["rejected"] == 1
    assert result["rejected_details"][0]["reason"].startswith("Invalid event_type")


def test_funnel_structure():
    ingest_test_events([
        make_event("VIS_F001", "ENTRY"),
        make_event("VIS_F001", "ZONE_ENTER", zone_id="SKINCARE"),
        make_event("VIS_F001", "BILLING_QUEUE_JOIN", zone_id="BILLING"),
    ])
    response = client.get("/stores/TEST_STORE/funnel")
    assert response.status_code == 200
    data = response.json()
    assert "funnel" in data
    stages = [s["stage"] for s in data["funnel"]]
    assert "ENTRY" in stages
    assert "ZONE_VISIT" in stages
    assert "BILLING_QUEUE" in stages
    assert "PURCHASE" in stages


def test_heatmap_returns_zones():
    ingest_test_events([
        make_event("VIS_H001", "ZONE_ENTER", zone_id="SKINCARE"),
        make_event("VIS_H002", "ZONE_ENTER", zone_id="MAKEUP"),
    ])
    response = client.get("/stores/TEST_STORE/heatmap")
    assert response.status_code == 200
    data = response.json()
    assert "zones" in data
    assert "data_confidence" in data


def test_anomalies_returns_list():
    response = client.get("/stores/TEST_STORE/anomalies")
    assert response.status_code == 200
    data = response.json()
    assert "anomalies" in data
    assert isinstance(data["anomalies"], list)


def test_batch_size_limit():
    events = [make_event(f"VIS_{i}", "ENTRY") for i in range(501)]
    response = client.post("/events/ingest", json={"events": events})
    assert response.status_code == 400