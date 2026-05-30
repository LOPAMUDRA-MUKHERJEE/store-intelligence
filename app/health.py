from sqlalchemy.orm import Session
from app.ingestion import EventDB
from datetime import datetime, timezone


def get_health(db: Session) -> dict:
    try:
        stores = db.query(EventDB.store_id).distinct().all()
        store_ids = [s[0] for s in stores]

        store_status = {}
        now = datetime.now(timezone.utc)

        for store_id in store_ids:
            last_event = db.query(EventDB).filter(
                EventDB.store_id == store_id
            ).order_by(EventDB.timestamp.desc()).first()

            if last_event:
                last_ts = last_event.timestamp
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                lag_minutes = (now - last_ts).seconds // 60
                store_status[store_id] = {
                    "last_event": last_event.timestamp.isoformat(),
                    "status": "STALE_FEED" if lag_minutes > 10 else "OK",
                    "lag_minutes": lag_minutes
                }

        return {
            "status": "healthy",
            "timestamp": now.isoformat(),
            "stores": store_status
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }