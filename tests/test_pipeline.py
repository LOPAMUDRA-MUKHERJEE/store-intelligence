# PROMPT: "Write pytest tests for a video detection pipeline that emits
# structured events. Test event schema validation, visitor ID generation,
# staff detection, re-entry detection, and cross-camera deduplication."
# CHANGES MADE: Updated to use actual store ID ST1008, adjusted signature
# threshold values based on real footage testing, added 60-second re-entry
# minimum gap test.

import pytest
import numpy as np
from datetime import datetime, timezone, timedelta
from pipeline.tracker import VisitorTracker
from pipeline.emit import make_event
from app.models import StoreEvent, VALID_EVENT_TYPES
import uuid


@pytest.fixture
def tracker():
    return VisitorTracker()


def make_fake_frame(color=(128, 128, 128)):
    frame = np.zeros((100, 50, 3), dtype=np.uint8)
    frame[:, :] = color
    return frame


def test_visitor_id_generated(tracker):
    frame = make_fake_frame()
    bbox = [0, 0, 50, 100]
    visitor_id, is_reentry, is_staff = tracker.process_track(
        1, bbox, frame, "ST1008", datetime.now(timezone.utc), "CAM3"
    )
    assert visitor_id.startswith("VIS_")
    assert is_reentry == False


def test_different_tracks_get_different_ids(tracker):
    frame1 = make_fake_frame(color=(200, 100, 50))
    frame2 = make_fake_frame(color=(50, 200, 150))
    bbox = [0, 0, 50, 100]
    now = datetime.now(timezone.utc)

    id1, _, _ = tracker.process_track(1, bbox, frame1, "ST1008", now, "CAM3")
    id2, _, _ = tracker.process_track(2, bbox, frame2, "ST1008", now, "CAM3")
    assert id1 != id2


def test_same_track_same_id(tracker):
    frame = make_fake_frame()
    bbox = [0, 0, 50, 100]
    now = datetime.now(timezone.utc)

    id1, _, _ = tracker.process_track(1, bbox, frame, "ST1008", now, "CAM3")
    id2, _, _ = tracker.process_track(1, bbox, frame, "ST1008", now, "CAM3")
    assert id1 == id2


def test_reentry_detected(tracker):
    frame = make_fake_frame(color=(100, 100, 100))
    bbox = [0, 0, 50, 100]
    now = datetime.now(timezone.utc)

    visitor_id, _, _ = tracker.process_track(1, bbox, frame, "ST1008", now, "CAM3")
    tracker.close_track(1, "CAM3", "ST1008", now)

    # Re-enter after 90 seconds
    later = now + timedelta(seconds=90)
    new_id, is_reentry, _ = tracker.process_track(2, bbox, frame, "ST1008", later, "CAM3")
    assert is_reentry == True
    assert new_id == visitor_id


def test_reentry_not_detected_too_soon(tracker):
    frame = make_fake_frame(color=(100, 100, 100))
    bbox = [0, 0, 50, 100]
    now = datetime.now(timezone.utc)

    tracker.process_track(1, bbox, frame, "ST1008", now, "CAM3")
    tracker.close_track(1, "CAM3", "ST1008", now)

    # Re-enter within 60 seconds — should NOT be re-entry
    soon = now + timedelta(seconds=30)
    _, is_reentry, _ = tracker.process_track(2, bbox, frame, "ST1008", soon, "CAM3")
    assert is_reentry == False


def test_event_schema_valid():
    event = make_event(
        store_id="ST1008",
        camera_id="CAM3",
        visitor_id="VIS_test01",
        event_type="ENTRY",
        timestamp=datetime.now(timezone.utc),
        confidence=0.9
    )
    parsed = StoreEvent(**event)
    assert parsed.store_id == "ST1008"
    assert parsed.event_type == "ENTRY"


def test_all_event_types_valid():
    for event_type in VALID_EVENT_TYPES:
        event = make_event(
            store_id="ST1008",
            camera_id="CAM3",
            visitor_id="VIS_test",
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            confidence=0.9
        )
        parsed = StoreEvent(**event)
        assert parsed.event_type == event_type


def test_event_id_unique():
    event1 = make_event("ST1008", "CAM3", "VIS_001", "ENTRY",
                        datetime.now(timezone.utc), confidence=0.9)
    event2 = make_event("ST1008", "CAM3", "VIS_002", "ENTRY",
                        datetime.now(timezone.utc), confidence=0.9)
    assert event1["event_id"] != event2["event_id"]


def test_low_confidence_not_suppressed():
    event = make_event(
        store_id="ST1008",
        camera_id="CAM3",
        visitor_id="VIS_lowconf",
        event_type="ENTRY",
        timestamp=datetime.now(timezone.utc),
        confidence=0.15
    )
    parsed = StoreEvent(**event)
    assert parsed.confidence == 0.15