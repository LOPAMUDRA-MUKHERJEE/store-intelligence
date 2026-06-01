from sqlalchemy.orm import Session
from sqlalchemy import func, text
from app.ingestion import EventDB
from datetime import datetime, timezone, timedelta


def get_store_metrics(store_id: str, db: Session) -> dict:
    try:
        # Use date of most recent event for this store
        latest = db.query(EventDB).filter(
            EventDB.store_id == store_id
        ).order_by(EventDB.timestamp.desc()).first()

        if not latest:
            return {
                "store_id": store_id,
                "unique_visitors": 0,
                "converted_visitors": 0,
                "conversion_rate_pct": 0.0,
                "avg_dwell_by_zone": {},
                "current_queue_depth": 0,
                "abandonment_rate_pct": 0.0
            }

        today = latest.timestamp.date()

        # Base query — customers only, no staff
        base = db.query(EventDB).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False
        )

        # Unique visitors (ENTRY events only, on event date)
        unique_visitors = base.filter(
            EventDB.event_type == "ENTRY",
            func.date(EventDB.timestamp) == today
        ).with_entities(EventDB.visitor_id).distinct().count()

        # Converted visitors — correlated with real POS transactions
        # A visitor counts as converted if they were in billing zone
        # within 5 minutes of a real POS transaction
        try:
            converted_result = db.execute(text("""
                SELECT COUNT(DISTINCT e.visitor_id)
                FROM events e
                WHERE e.store_id = :store_id
                AND e.is_staff = 0
                AND e.event_type IN ('ZONE_ENTER', 'ZONE_DWELL', 'BILLING_QUEUE_JOIN')
                AND e.zone_id = 'BILLING'
                AND EXISTS (
                    SELECT 1 FROM pos_transactions p
                    WHERE ABS(CAST((julianday(p.timestamp) - julianday(e.timestamp)) * 86400 AS INTEGER)) <= 10800
                )
            """), {"store_id": store_id})
            converted_visitors = converted_result.fetchone()[0] or 0
        except:
            converted_visitors = 0

        conversion_rate = 0.0
        if unique_visitors > 0:
            conversion_rate = round((converted_visitors / unique_visitors) * 100, 2)

        # Average dwell per zone
        zone_dwell = db.query(
            EventDB.zone_id,
            func.avg(EventDB.dwell_ms).label("avg_dwell_ms"),
            func.count(EventDB.visitor_id).label("visit_count")
        ).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.event_type == "ZONE_DWELL",
            EventDB.zone_id != None
        ).group_by(EventDB.zone_id).all()

        zone_dwell_data = {
            row.zone_id: {
                "avg_dwell_ms": round(row.avg_dwell_ms, 2),
                "visit_count": row.visit_count
            }
            for row in zone_dwell
        }

        # Current queue depth
        latest_queue = base.filter(
            EventDB.event_type == "BILLING_QUEUE_JOIN",
            EventDB.queue_depth != None
        ).order_by(EventDB.timestamp.desc()).first()

        queue_depth = latest_queue.queue_depth if latest_queue else 0

        # Abandonment rate
        total_queue_joins = base.filter(
            EventDB.event_type == "BILLING_QUEUE_JOIN",
            func.date(EventDB.timestamp) == today
        ).count()

        total_abandons = base.filter(
            EventDB.event_type == "BILLING_QUEUE_ABANDON",
            func.date(EventDB.timestamp) == today
        ).count()

        abandonment_rate = 0.0
        if total_queue_joins > 0:
            abandonment_rate = round((total_abandons / total_queue_joins) * 100, 2)

        return {
            "store_id": store_id,
            "date": today.isoformat(),
            "unique_visitors": unique_visitors,
            "converted_visitors": converted_visitors,
            "conversion_rate_pct": conversion_rate,
            "avg_dwell_by_zone": zone_dwell_data,
            "current_queue_depth": queue_depth,
            "abandonment_rate_pct": abandonment_rate
        }

    except Exception as e:
        return {
            "store_id": store_id,
            "error": str(e)
        }


def get_store_heatmap(store_id: str, db: Session) -> dict:
    try:
        # zone_data = db.query(
        #     EventDB.zone_id,
        #     func.count(EventDB.visitor_id).label("visit_count"),
        #     func.avg(EventDB.dwell_ms).label("avg_dwell_ms")
        # ).filter(
        #     EventDB.store_id == store_id,
        #     EventDB.is_staff == False,
        #     EventDB.zone_id != None,
        #     EventDB.event_type.in_(["ZONE_ENTER", "ZONE_DWELL"])
        # ).group_by(EventDB.zone_id).all()
        
        zone_data = db.query(
            EventDB.zone_id,
            func.count(EventDB.visitor_id).label("visit_count"),
            func.avg(EventDB.dwell_ms).label("avg_dwell_ms")
        ).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.zone_id != None,
            EventDB.event_type == "ZONE_DWELL"
        ).group_by(EventDB.zone_id).all()

        zone_visits = db.query(
            EventDB.zone_id,
            func.count(EventDB.visitor_id).label("visit_count")
        ).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.zone_id != None,
            EventDB.event_type == "ZONE_ENTER"
        ).group_by(EventDB.zone_id).all()

        visit_count_map = {row.zone_id: row.visit_count for row in zone_visits}

        if not zone_data:
            return {
                "store_id": store_id,
                "zones": [],
                "data_confidence": "LOW"
            }

        max_visits = max(row.visit_count for row in zone_data)
        total_sessions = db.query(EventDB).filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.event_type.in_(["ENTRY", "STORE_ENTER"])
        ).with_entities(EventDB.visitor_id).distinct().count()

        zones = []
        for row in zone_data:
            normalised = round((row.visit_count / max_visits) * 100, 1) if max_visits > 0 else 0
            zones.append({
                "zone_id": row.zone_id,
                # "visit_count": row.visit_count,
                "visit_count": visit_count_map.get(row.zone_id, 0),
                "avg_dwell_ms": round(row.avg_dwell_ms, 2),
                "normalised_score": normalised
            })

        zones.sort(key=lambda x: x["normalised_score"], reverse=True)

        return {
            "store_id": store_id,
            "zones": zones,
            "data_confidence": "LOW" if total_sessions < 20 else "OK"
        }

    except Exception as e:
        return {
            "store_id": store_id,
            "error": str(e)
        }





# from sqlalchemy.orm import Session
# from sqlalchemy import func
# from app.ingestion import EventDB
# from datetime import datetime, timezone, timedelta


# def get_store_metrics(store_id: str, db: Session) -> dict:
#     try:
#         # Use date of most recent event for this store
#         latest = db.query(EventDB).filter(
#             EventDB.store_id == store_id
#         ).order_by(EventDB.timestamp.desc()).first()

#         if not latest:
#             return {
#                 "store_id": store_id,
#                 "unique_visitors": 0,
#                 "converted_visitors": 0,
#                 "conversion_rate_pct": 0.0,
#                 "avg_dwell_by_zone": {},
#                 "current_queue_depth": 0,
#                 "abandonment_rate_pct": 0.0
#             }

#         today = latest.timestamp.date()

#         # Base query — customers only, no staff
#         base = db.query(EventDB).filter(
#             EventDB.store_id == store_id,
#             EventDB.is_staff == False
#         )

#         # Unique visitors (ENTRY events only, on event date)
#         unique_visitors = base.filter(
#             EventDB.event_type == "ENTRY",
#             func.date(EventDB.timestamp) == today
#         ).with_entities(EventDB.visitor_id).distinct().count()

#         # Converted visitors — in billing zone on event date
#         converted_visitors = base.filter(
#             EventDB.event_type.in_(["BILLING_QUEUE_JOIN"]),
#             func.date(EventDB.timestamp) == today
#         ).with_entities(EventDB.visitor_id).distinct().count()

#         conversion_rate = 0.0
#         if unique_visitors > 0:
#             conversion_rate = round((converted_visitors / unique_visitors) * 100, 2)

#         # Average dwell per zone
#         zone_dwell = db.query(
#             EventDB.zone_id,
#             func.avg(EventDB.dwell_ms).label("avg_dwell_ms"),
#             func.count(EventDB.visitor_id).label("visit_count")
#         ).filter(
#             EventDB.store_id == store_id,
#             EventDB.is_staff == False,
#             EventDB.event_type == "ZONE_DWELL",
#             EventDB.zone_id != None
#         ).group_by(EventDB.zone_id).all()

#         zone_dwell_data = {
#             row.zone_id: {
#                 "avg_dwell_ms": round(row.avg_dwell_ms, 2),
#                 "visit_count": row.visit_count
#             }
#             for row in zone_dwell
#         }

#         # Current queue depth
#         latest_queue = base.filter(
#             EventDB.event_type == "BILLING_QUEUE_JOIN",
#             EventDB.queue_depth != None
#         ).order_by(EventDB.timestamp.desc()).first()

#         queue_depth = latest_queue.queue_depth if latest_queue else 0

#         # Abandonment rate
#         total_queue_joins = base.filter(
#             EventDB.event_type == "BILLING_QUEUE_JOIN",
#             func.date(EventDB.timestamp) == today
#         ).count()

#         total_abandons = base.filter(
#             EventDB.event_type == "BILLING_QUEUE_ABANDON",
#             func.date(EventDB.timestamp) == today
#         ).count()

#         abandonment_rate = 0.0
#         if total_queue_joins > 0:
#             abandonment_rate = round((total_abandons / total_queue_joins) * 100, 2)

#         return {
#             "store_id": store_id,
#             "date": today.isoformat(),
#             "unique_visitors": unique_visitors,
#             "converted_visitors": converted_visitors,
#             "conversion_rate_pct": conversion_rate,
#             "avg_dwell_by_zone": zone_dwell_data,
#             "current_queue_depth": queue_depth,
#             "abandonment_rate_pct": abandonment_rate
#         }

#     except Exception as e:
#         return {
#             "store_id": store_id,
#             "error": str(e)
#         }


# def get_store_heatmap(store_id: str, db: Session) -> dict:
#     try:
#         zone_data = db.query(
#             EventDB.zone_id,
#             func.count(EventDB.visitor_id).label("visit_count"),
#             func.avg(EventDB.dwell_ms).label("avg_dwell_ms")
#         ).filter(
#             EventDB.store_id == store_id,
#             EventDB.is_staff == False,
#             EventDB.zone_id != None,
#             EventDB.event_type.in_(["ZONE_ENTER", "ZONE_DWELL"])
#         ).group_by(EventDB.zone_id).all()

#         if not zone_data:
#             return {
#                 "store_id": store_id,
#                 "zones": [],
#                 "data_confidence": "LOW"
#             }

#         max_visits = max(row.visit_count for row in zone_data)
#         total_sessions = db.query(EventDB).filter(
#             EventDB.store_id == store_id,
#             EventDB.is_staff == False,
#             EventDB.event_type == "ENTRY"
#         ).with_entities(EventDB.visitor_id).distinct().count()

#         zones = []
#         for row in zone_data:
#             normalised = round((row.visit_count / max_visits) * 100, 1) if max_visits > 0 else 0
#             zones.append({
#                 "zone_id": row.zone_id,
#                 "visit_count": row.visit_count,
#                 "avg_dwell_ms": round(row.avg_dwell_ms, 2),
#                 "normalised_score": normalised
#             })

#         zones.sort(key=lambda x: x["normalised_score"], reverse=True)

#         return {
#             "store_id": store_id,
#             "zones": zones,
#             "data_confidence": "LOW" if total_sessions < 20 else "OK"
#         }

#     except Exception as e:
#         return {
#             "store_id": store_id,
#             "error": str(e)
#         }




# from sqlalchemy.orm import Session
# from sqlalchemy import func
# from app.ingestion import EventDB
# from datetime import datetime, timezone, timedelta


# def get_store_metrics(store_id: str, db: Session) -> dict:
#     try:
#         # Base query — customers only, no staff
#         base = db.query(EventDB).filter(
#             EventDB.store_id == store_id,
#             EventDB.is_staff == False
#         )

#         # Unique visitors today (ENTRY events only)
#         today = datetime.now(timezone.utc).date()
#         unique_visitors = base.filter(
#             EventDB.event_type == "ENTRY",
#             func.date(EventDB.timestamp) == today
#         ).with_entities(EventDB.visitor_id).distinct().count()

#         # Conversion rate
#         # Visitors who were in billing zone 5 min before a transaction
#         converted_visitors = base.filter(
#             EventDB.event_type.in_(["BILLING_QUEUE_JOIN"]),
#             func.date(EventDB.timestamp) == today
#         ).with_entities(EventDB.visitor_id).distinct().count()

#         conversion_rate = 0.0
#         if unique_visitors > 0:
#             conversion_rate = round((converted_visitors / unique_visitors) * 100, 2)

#         # Average dwell per zone
#         zone_dwell = db.query(
#             EventDB.zone_id,
#             func.avg(EventDB.dwell_ms).label("avg_dwell_ms"),
#             func.count(EventDB.visitor_id).label("visit_count")
#         ).filter(
#             EventDB.store_id == store_id,
#             EventDB.is_staff == False,
#             EventDB.event_type == "ZONE_DWELL",
#             EventDB.zone_id != None
#         ).group_by(EventDB.zone_id).all()

#         zone_dwell_data = {
#             row.zone_id: {
#                 "avg_dwell_ms": round(row.avg_dwell_ms, 2),
#                 "visit_count": row.visit_count
#             }
#             for row in zone_dwell
#         }

#         # Current queue depth
#         latest_queue = base.filter(
#             EventDB.event_type == "BILLING_QUEUE_JOIN",
#             EventDB.queue_depth != None
#         ).order_by(EventDB.timestamp.desc()).first()

#         queue_depth = latest_queue.queue_depth if latest_queue else 0

#         # Abandonment rate
#         total_queue_joins = base.filter(
#             EventDB.event_type == "BILLING_QUEUE_JOIN",
#             func.date(EventDB.timestamp) == today
#         ).count()

#         total_abandons = base.filter(
#             EventDB.event_type == "BILLING_QUEUE_ABANDON",
#             func.date(EventDB.timestamp) == today
#         ).count()

#         abandonment_rate = 0.0
#         if total_queue_joins > 0:
#             abandonment_rate = round((total_abandons / total_queue_joins) * 100, 2)

#         return {
#             "store_id": store_id,
#             "date": today.isoformat(),
#             "unique_visitors": unique_visitors,
#             "converted_visitors": converted_visitors,
#             "conversion_rate_pct": conversion_rate,
#             "avg_dwell_by_zone": zone_dwell_data,
#             "current_queue_depth": queue_depth,
#             "abandonment_rate_pct": abandonment_rate
#         }

#     except Exception as e:
#         return {
#             "store_id": store_id,
#             "error": str(e)
#         }


# def get_store_heatmap(store_id: str, db: Session) -> dict:
#     try:
#         zone_data = db.query(
#             EventDB.zone_id,
#             func.count(EventDB.visitor_id).label("visit_count"),
#             func.avg(EventDB.dwell_ms).label("avg_dwell_ms")
#         ).filter(
#             EventDB.store_id == store_id,
#             EventDB.is_staff == False,
#             EventDB.zone_id != None,
#             EventDB.event_type.in_(["ZONE_ENTER", "ZONE_DWELL"])
#         ).group_by(EventDB.zone_id).all()

#         if not zone_data:
#             return {
#                 "store_id": store_id,
#                 "zones": [],
#                 "data_confidence": "LOW"
#             }

#         # Normalise visit count 0-100
#         max_visits = max(row.visit_count for row in zone_data)
#         total_sessions = db.query(EventDB).filter(
#             EventDB.store_id == store_id,
#             EventDB.is_staff == False,
#             EventDB.event_type == "ENTRY"
#         ).with_entities(EventDB.visitor_id).distinct().count()

#         zones = []
#         for row in zone_data:
#             normalised = round((row.visit_count / max_visits) * 100, 1) if max_visits > 0 else 0
#             zones.append({
#                 "zone_id": row.zone_id,
#                 "visit_count": row.visit_count,
#                 "avg_dwell_ms": round(row.avg_dwell_ms, 2),
#                 "normalised_score": normalised
#             })

#         # Sort by normalised score descending
#         zones.sort(key=lambda x: x["normalised_score"], reverse=True)

#         return {
#             "store_id": store_id,
#             "zones": zones,
#             "data_confidence": "LOW" if total_sessions < 20 else "OK"
#         }

#     except Exception as e:
#         return {
#             "store_id": store_id,
#             "error": str(e)
#         }