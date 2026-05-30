import pandas as pd
from sqlalchemy import create_engine, Column, String, Float, DateTime, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = "sqlite:////tmp/store_intelligence.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)


class POSTransaction(Base):
    __tablename__ = "pos_transactions"

    invoice_number = Column(String, primary_key=True)
    store_id = Column(String, index=True)
    store_name = Column(String)
    order_date = Column(String)
    order_time = Column(String)
    timestamp = Column(DateTime, index=True)
    total_amount = Column(Float)
    customer_number = Column(String)
    salesperson_id = Column(String)


def create_pos_table():
    Base.metadata.create_all(bind=engine)


def ingest_pos_csv(csv_path: str):
    create_pos_table()
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    db = SessionLocal()
    inserted = 0
    skipped = 0

    for _, row in df.iterrows():
        try:
            date_str = str(row["order_date"]).strip()
            time_str = str(row["order_time"]).strip()
            timestamp = datetime.strptime(f"{date_str} {time_str}", "%d-%m-%Y %H:%M:%S")

            existing = db.query(POSTransaction).filter(
                POSTransaction.invoice_number == str(row["invoice_number"])
            ).first()

            if existing:
                skipped += 1
                continue

            txn = POSTransaction(
                invoice_number=str(row["invoice_number"]),
                store_id=str(row["store_id"]),
                store_name=str(row["store_name"]),
                order_date=date_str,
                order_time=time_str,
                timestamp=timestamp,
                total_amount=float(row["total_amount"]),
                customer_number=str(row.get("customer_number", "")),
                salesperson_id=str(row.get("salesperson_id", ""))
            )

            db.add(txn)
            inserted += 1

        except Exception as e:
            print(f"Skipping row: {e}")
            skipped += 1
            continue

    db.commit()
    db.close()
    print(f"POS ingestion done — inserted: {inserted}, skipped: {skipped}")


if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "Brigade_Bangalore_10_April_26 (1)bc6219c.csv"