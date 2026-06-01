# Store Intelligence System

A complete pipeline that converts raw CCTV footage into live store analytics for Purplle

**Store:** ST1008 — Brigade Road, Bangalore  
**Dataset:** April 10, 2026

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
curl http://localhost:8000/stores/ST1008/heatmap
curl http://localhost:8000/stores/ST1008/funnel
curl http://localhost:8000/stores/ST1008/anomalies
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

### Sample `/metrics` response

```json
{
  "store_id": "ST1008",
  "date": "2026-04-10",
  "unique_visitors": 12,
  "converted_visitors": 3,
  "conversion_rate": 0.25,
  "avg_dwell_by_zone": {
    "SKINCARE": 84300,
    "MAKEUP": 61200,
    "BILLING": 42000
  },
  "peak_hour": "20"
}
```

### Sample `/funnel` response

```json
{
  "store_id": "ST1008",
  "funnel": [
    { "stage": "STORE_ENTER", "visitors": 12, "drop_off_pct": 0 },
    { "stage": "BROWSING_ZONE", "visitors": 9, "drop_off_pct": 25 },
    { "stage": "BILLING_ZONE", "visitors": 5, "drop_off_pct": 44 },
    { "stage": "CONVERTED", "visitors": 3, "drop_off_pct": 40 }
  ]
}
```

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
|── pos_data.csv         # 24 transactions, April 10 2026, 13:00–19:00
└── README.md

## Detection Pipeline Details

| Component | Detail |
|---|---|
| Model | YOLOv8n — CPU-compatible person detection |
| Tracker | Custom ByteTrack — persistent IDs + lost-track buffer |
| Re-ID | 16-bin HSV histogram of torso region |
| Staff filtering | Black uniform (HSV) + stationary 60s in billing zone |
| Group detection | Implemented; disabled on CAM3 due to door boundary noise |
| Re-entry guard | 60-second minimum gap before re-matching exited signatures |
| Cross-camera dedup | Signatures shared across cameras per store session |
| Entry/exit line | 75% frame height threshold |
| Frame sampling | Every 3rd frame (5fps effective) |
| ZONE_DWELL interval | 10 seconds |


## Key Design Decisions

See `docs/DESIGN.md` and `docs/CHOICES.md` for full reasoning.

## Store Layout

Single store: `ST1008` — Brigade Road, Bangalore

Zones: SKINCARE (CAM1), MAKEUP + FLOOR_MAIN (CAM2), BILLING (CAM5)

## Notes

- CAM4 is a storage room — excluded from pipeline
- Database persists at `/app/store_intelligence.db` via Docker volume
- POS data loaded automatically on API startup

## Known Limitations

- **POS timestamp mismatch** — POS data (13:00–19:00) and footage (20:10+) don't overlap. Correlation window widened to 3 hours for this dataset. Production would use aligned clocks with a 5-minute window.
- **Short clips (~2 min)** — dwell times underestimate real browsing behaviour. Full-shift footage gives accurate results.
- **Dead zone anomalies** — will fire on short historical clips. Expected and documented.
- **No bag detection** — conversion relies on POS matching only. Detecting shopping bags at the counter would add a camera-side conversion signal.
