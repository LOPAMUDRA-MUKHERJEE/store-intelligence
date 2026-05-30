from sqlalchemy.orm import Session
from sqlalchemy import func
from app.ingestion import EventDB
from datetime import datetime, timezone, timedelta


def get_store_anomalies(store_id: str, db: Session) -> dict:
    try:
        now = datetime.now(timezone.utc)
        today = now.date()
        anomalies = []

        # 1. Queue spike — queue depth > 5
        latest_queue = db.query(EventDB).filter(
            EventDB.store_id == store_id,
            EventDB.event_type == "BILLING_QUEUE_JOIN",
            EventDB.queue_depth != None
        ).order_by(EventDB.timestamp.desc()).first()

        if latest_queue and latest_queue.queue_depth > 5:
            anomalies.append({
                "type": "BILLING_QUEUE_SPIKE",
                "severity": "CRITICAL" if latest_queue.queue_depth > 8 else "WARN",
                "details": f"Queue depth is {latest_queue.queue_depth}",
                "suggested_action": "Open additional billing counter immediately"
            })

        # 2. Dead zone — no visits in last 30 minutes
        thirty_min_ago = now - timedelta(minutes=30)
        recent_zones = db.query(EventDB.zone_id).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.event_type.in_(["ZONE_ENTER", "ZONE_DWELL"]),
            EventDB.timestamp >= thirty_min_ago
        ).distinct().all()

        active_zones = {row.zone_id for row in recent_zones if row.zone_id}

        all_zones = db.query(EventDB.zone_id).filter(
            EventDB.store_id == store_id,
            EventDB.zone_id != None
        ).distinct().all()

        all_zone_ids = {row.zone_id for row in all_zones}
        dead_zones = all_zone_ids - active_zones

        for zone in dead_zones:
            anomalies.append({
                "type": "DEAD_ZONE",
                "severity": "INFO",
                "details": f"Zone {zone} has had no visits in the last 30 minutes",
                "suggested_action": f"Check if zone {zone} display needs refreshing"
            })

        # 3. Conversion drop vs 7-day average
        seven_days_ago = now - timedelta(days=7)

        recent_entries = db.query(EventDB.visitor_id).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.event_type == "ENTRY",
            func.date(EventDB.timestamp) == today
        ).distinct().count()

        recent_conversions = db.query(EventDB.visitor_id).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.event_type == "BILLING_QUEUE_JOIN",
            func.date(EventDB.timestamp) == today
        ).distinct().count()

        today_rate = (recent_conversions / recent_entries * 100) if recent_entries > 0 else 0

        historical_entries = db.query(EventDB.visitor_id).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.event_type == "ENTRY",
            EventDB.timestamp >= seven_days_ago,
            func.date(EventDB.timestamp) != today
        ).distinct().count()

        historical_conversions = db.query(EventDB.visitor_id).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.event_type == "BILLING_QUEUE_JOIN",
            EventDB.timestamp >= seven_days_ago,
            func.date(EventDB.timestamp) != today
        ).distinct().count()

        historical_rate = (historical_conversions / historical_entries * 100) if historical_entries > 0 else 0

        if historical_rate > 0:
            drop_pct = ((historical_rate - today_rate) / historical_rate) * 100
            if drop_pct > 20:
                anomalies.append({
                    "type": "CONVERSION_DROP",
                    "severity": "CRITICAL" if drop_pct > 40 else "WARN",
                    "details": f"Conversion rate dropped {round(drop_pct, 1)}% vs 7-day average",
                    "suggested_action": "Review staffing levels and zone layouts"
                })

        return {
            "store_id": store_id,
            "timestamp": now.isoformat(),
            "anomalies": anomalies
        }

    except Exception as e:
        return {
            "store_id": store_id,
            "error": str(e)
        }