from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from app.models import StoreEvent, VALID_EVENT_TYPES
import logging

logger = logging.getLogger(__name__)

# Database setup
# DATABASE_URL = "sqlite:///./store_intelligence.db"
# DATABASE_URL = "sqlite:////app/data/store_intelligence.db"
DATABASE_URL = "sqlite:////tmp/store_intelligence.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Database table definition
class EventDB(Base):
    __tablename__ = "events"

    event_id = Column(String, primary_key=True, index=True)
    store_id = Column(String, index=True)
    camera_id = Column(String)
    visitor_id = Column(String, index=True)
    event_type = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    zone_id = Column(String, nullable=True)
    dwell_ms = Column(Integer, default=0)
    is_staff = Column(Boolean, default=False)
    confidence = Column(Float)
    queue_depth = Column(Integer, nullable=True)
    sku_zone = Column(String, nullable=True)
    session_seq = Column(Integer, nullable=True)


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ingest_events(events: list[StoreEvent], db) -> dict:
    accepted = []
    rejected = []

    for event in events:
        # Validate event type
        if event.event_type not in VALID_EVENT_TYPES:
            rejected.append({
                "event_id": event.event_id,
                "reason": f"Invalid event_type: {event.event_type}"
            })
            continue

        # Check for duplicate (idempotency)
        existing = db.query(EventDB).filter(
            EventDB.event_id == event.event_id
        ).first()

        if existing:
            # Not an error — idempotent by design
            accepted.append(event.event_id)
            continue

        # Store the event
        db_event = EventDB(
            event_id=event.event_id,
            store_id=event.store_id,
            camera_id=event.camera_id,
            visitor_id=event.visitor_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            zone_id=event.zone_id,
            dwell_ms=event.dwell_ms,
            is_staff=event.is_staff,
            confidence=event.confidence,
            queue_depth=event.metadata.queue_depth,
            sku_zone=event.metadata.sku_zone,
            session_seq=event.metadata.session_seq
        )

        db.add(db_event)
        accepted.append(event.event_id)

    db.commit()

    logger.info(f"Ingested {len(accepted)} events, rejected {len(rejected)}")

    return {
        "accepted": len(accepted),
        "rejected": len(rejected),
        "rejected_details": rejected
    }