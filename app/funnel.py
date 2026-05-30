from sqlalchemy.orm import Session
from app.ingestion import EventDB
from datetime import datetime, timezone


def get_store_funnel(store_id: str, db: Session) -> dict:
    try:
        today = datetime.now(timezone.utc).date()

        # All customer visitor IDs who entered today
        entries = db.query(EventDB.visitor_id).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.event_type == "ENTRY",
        ).distinct().all()

        entry_ids = {row.visitor_id for row in entries}
        total_entries = len(entry_ids)

        # Visited any zone
        zone_visitors = db.query(EventDB.visitor_id).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.event_type.in_(["ZONE_ENTER", "ZONE_DWELL"]),
            EventDB.visitor_id.in_(entry_ids)
        ).distinct().all()

        zone_visit_ids = {row.visitor_id for row in zone_visitors}
        total_zone_visits = len(zone_visit_ids)

        # Reached billing queue
        billing_visitors = db.query(EventDB.visitor_id).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.event_type == "BILLING_QUEUE_JOIN",
            EventDB.visitor_id.in_(entry_ids)
        ).distinct().all()

        billing_ids = {row.visitor_id for row in billing_visitors}
        total_billing = len(billing_ids)

        # Purchased (no abandon after billing)
        abandoned = db.query(EventDB.visitor_id).filter(
            EventDB.store_id == store_id,
            EventDB.event_type == "BILLING_QUEUE_ABANDON",
            EventDB.visitor_id.in_(billing_ids)
        ).distinct().all()

        abandoned_ids = {row.visitor_id for row in abandoned}
        purchased_ids = billing_ids - abandoned_ids
        total_purchased = len(purchased_ids)

        # Drop-off percentages
        def dropoff(a, b):
            if a == 0:
                return 0.0
            return round((1 - b / a) * 100, 2)

        return {
            "store_id": store_id,
            "funnel": [
                {
                    "stage": "ENTRY",
                    "visitors": total_entries,
                    "dropoff_pct": 0.0
                },
                {
                    "stage": "ZONE_VISIT",
                    "visitors": total_zone_visits,
                    "dropoff_pct": dropoff(total_entries, total_zone_visits)
                },
                {
                    "stage": "BILLING_QUEUE",
                    "visitors": total_billing,
                    "dropoff_pct": dropoff(total_zone_visits, total_billing)
                },
                {
                    "stage": "PURCHASE",
                    "visitors": total_purchased,
                    "dropoff_pct": dropoff(total_billing, total_purchased)
                }
            ]
        }

    except Exception as e:
        return {
            "store_id": store_id,
            "error": str(e)
        }