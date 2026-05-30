import json
import uuid
import requests
from datetime import datetime, timezone


API_URL = "http://127.0.0.1:8000/events/ingest"


def make_event(
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    timestamp: datetime,
    zone_id: str = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 1.0,
    queue_depth: int = None,
    sku_zone: str = None,
    session_seq: int = 0
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": timestamp.isoformat(),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": confidence,
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": sku_zone,
            "session_seq": session_seq
        }
    }


def emit_events(events: list[dict]) -> dict:
    if not events:
        return {}
    
    payload = {"events": events}
    
    try:
        response = requests.post(
            API_URL,
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        print("API not reachable — are you running docker compose up?")
        return {}
    except Exception as e:
        print(f"Emit error: {e}")
        return {}


def format_timestamp(clip_start: datetime, frame_number: int, fps: float = 15.0) -> datetime:
    offset_seconds = frame_number / fps
    return clip_start.replace(tzinfo=timezone.utc) + __import__('datetime').timedelta(seconds=offset_seconds)