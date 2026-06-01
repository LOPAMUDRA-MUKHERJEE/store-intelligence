# Store Intelligence System

A complete pipeline that converts raw CCTV footage into live store analytics for Apex Retail.

## Architecture
CCTV Videos → Detection Pipeline → Event Stream → Intelligence API → Live Metrics

## Setup

### Prerequisites
- Docker Desktop
- Python 3.11+
- Git

### 1. Clone the repository

```bash
git clone https://github.com/LOPAMUDRA-MUKHERJEE/store-intelligence.git
cd store-intelligence
```

### 2. Add required files (not in repo due to licensing)

Place the following in the project root:
- `CCTV Footage/` — folder containing CAM 1.mp4 through CAM 5.mp4
- `pos_data.csv` — POS transactions CSV

### 3. Start the API

```bash
docker compose up --build
```

API will be available at `http://localhost:8000`

### 4. Run the detection pipeline

In a separate terminal:

```bash
pip install -r requirements.txt
python pipeline/run_all.py
```

This processes all camera clips and pushes events into the API automatically.

### 5. Verify

```bash
curl http://localhost:8000/health
curl http://localhost:8000/stores/ST1008/metrics
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /events/ingest` | Ingest batch of up to 500 events |
| `GET /stores/{id}/metrics` | Unique visitors, conversion rate, dwell, queue |
| `GET /stores/{id}/funnel` | Entry → Zone → Billing → Purchase funnel |
| `GET /stores/{id}/heatmap` | Zone visit frequency normalised 0-100 |
| `GET /stores/{id}/anomalies` | Queue spikes, dead zones, conversion drops |
| `GET /health` | Service status and feed lag per store |

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

## Project Structure
store-intelligence/
├── pipeline/
│   ├── detect.py        # YOLO detection + tracking
│   ├── tracker.py       # Re-ID and cross-camera deduplication
│   ├── emit.py          # Event schema and API emission
│   ├── ingest_pos.py    # POS data ingestion
│   └── run_all.py       # Process all clips in sequence
├── app/
│   ├── main.py          # FastAPI entrypoint
│   ├── models.py        # Pydantic event schema
│   ├── ingestion.py     # Database and ingest logic
│   ├── metrics.py       # Real-time metric computation
│   ├── funnel.py        # Conversion funnel logic
│   ├── anomalies.py     # Anomaly detection
│   └── health.py        # Health endpoint
├── tests/
│   ├── test_pipeline.py
│   ├── test_metrics.py
│   └── test_anomalies.py
├── docs/
│   ├── DESIGN.md
│   └── CHOICES.md
├── docker-compose.yml
├── Dockerfile
├── store_layout.json
└── README.md

## Detection Pipeline Details

- **Model:** YOLOv8n — fast CPU-compatible person detection
- **Tracker:** ByteTrack — persistent identity across frames
- **Re-ID:** 16-bin colour histogram signatures for cross-camera deduplication
- **Staff detection:** Combined black uniform colour signal + movement pattern
- **Entry/exit:** Vertical threshold crossing at 75% frame height

## Key Design Decisions

See `docs/DESIGN.md` and `docs/CHOICES.md` for full reasoning.

## Store Layout

Single store: `ST1008` — Brigade Road, Bangalore

Zones: SKINCARE (CAM1), MAKEUP + FLOOR_MAIN (CAM2), BILLING (CAM5)

## Notes

- CAM4 is a storage room — excluded from pipeline
- Database persists at `/app/store_intelligence.db` via Docker volume
- POS data loaded automatically on API startup
