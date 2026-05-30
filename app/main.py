from fastapi import FastAPI, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime
import time
import uuid
import logging

from app.models import EventBatch
from app.ingestion import get_db, create_tables, ingest_events
from app.metrics import get_store_metrics
from app.funnel import get_store_funnel
from app.anomalies import get_store_anomalies
from app.health import get_health

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Store Intelligence API", version="1.0.0")

# Create tables on startup
# @app.on_event("startup")
# def startup():
#     create_tables()
#     logger.info("Database tables created")

@app.on_event("startup")
def startup():
    create_tables()
    logger.info("Database tables created")
    # Load POS transactions on startup
    try:
        import pandas as pd
        from sqlalchemy import Column, String, Float, DateTime
        from app.ingestion import SessionLocal, Base, engine
        
        # Create POS table
        from sqlalchemy import Table, MetaData
        meta = MetaData()
        pos_table = Table('pos_transactions', meta,
            Column('invoice_number', String, primary_key=True),
            Column('store_id', String),
            Column('store_name', String),
            Column('order_date', String),
            Column('order_time', String),
            Column('timestamp', DateTime),
            Column('total_amount', Float),
            Column('customer_number', String),
            Column('salesperson_id', String),
        )
        meta.create_all(engine)

        df = pd.read_csv("/app/pos_data.csv")
        df.columns = df.columns.str.strip()

        db = SessionLocal()
        inserted = 0

        for _, row in df.iterrows():
            try:
                from datetime import datetime
                date_str = str(row["order_date"]).strip()
                time_str = str(row["order_time"]).strip()
                timestamp = datetime.strptime(f"{date_str} {time_str}", "%d-%m-%Y %H:%M:%S")

                exists = db.execute(
                    pos_table.select().where(
                        pos_table.c.invoice_number == str(row["invoice_number"])
                    )
                ).fetchone()

                if exists:
                    continue

                db.execute(pos_table.insert().values(
                    invoice_number=str(row["invoice_number"]),
                    store_id=str(row["store_id"]),
                    store_name=str(row["store_name"]),
                    order_date=date_str,
                    order_time=time_str,
                    timestamp=timestamp,
                    total_amount=float(row["total_amount"]),
                    customer_number=str(row.get("customer_number", "")),
                    salesperson_id=str(row.get("salesperson_id", ""))
                ))
                inserted += 1

            except Exception as e:
                continue

        db.commit()
        db.close()
        logger.info(f"POS data loaded: {inserted} transactions")

    except Exception as e:
        logger.warning(f"POS data not loaded: {e}")


# Middleware for structured logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id = str(uuid.uuid4())[:8]
    start = time.time()
    response = await call_next(request)
    latency = round((time.time() - start) * 1000, 2)
    logger.info(
        f"trace_id={trace_id} endpoint={request.url.path} "
        f"method={request.method} status={response.status_code} "
        f"latency_ms={latency}"
    )
    return response


# POST /events/ingest
@app.post("/events/ingest")
async def ingest(batch: EventBatch, db: Session = Depends(get_db)):
    if len(batch.events) > 500:
        raise HTTPException(
            status_code=400,
            detail="Batch size exceeds 500 events"
        )
    result = ingest_events(batch.events, db)
    return result


# GET /stores/{id}/metrics
@app.get("/stores/{store_id}/metrics")
async def metrics(store_id: str, db: Session = Depends(get_db)):
    return get_store_metrics(store_id, db)


# GET /stores/{id}/funnel
@app.get("/stores/{store_id}/funnel")
async def funnel(store_id: str, db: Session = Depends(get_db)):
    return get_store_funnel(store_id, db)


# GET /stores/{id}/heatmap
@app.get("/stores/{store_id}/heatmap")
async def heatmap(store_id: str, db: Session = Depends(get_db)):
    from app.metrics import get_store_heatmap
    return get_store_heatmap(store_id, db)


# GET /stores/{id}/anomalies
@app.get("/stores/{store_id}/anomalies")
async def anomalies(store_id: str, db: Session = Depends(get_db)):
    return get_store_anomalies(store_id, db)


# GET /health
@app.get("/health")
async def health(db: Session = Depends(get_db)):
    return get_health(db)