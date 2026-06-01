# DESIGN.md — Store Intelligence System

## Architecture Overview

The system is a four-stage pipeline that converts raw CCTV footage into live store analytics.

CCTV Videos → Detection Pipeline → Event Stream → Intelligence API → Dashboard

### Stage 1: Detection Pipeline (`pipeline/`)

The detection pipeline processes raw video clips using YOLOv8n for person detection and a custom ByteTrack-based tracker for cross-frame identity persistence. Each camera clip is processed independently, with a shared `VisitorTracker` instance maintaining identity across cameras for the same store.

**Key design decisions:**
- YOLOv8n chosen for speed vs accuracy trade-off — nano model processes 2-minute clips in under 2 minutes on CPU
- Every 3rd frame processed to balance accuracy with performance
- Appearance signatures use 16-bin colour histograms of the person's torso region
- Entry/exit determined by vertical movement crossing a configurable threshold line

**Edge cases handled:**
- Re-entry: minimum 60 second gap enforced before matching exited visitor signatures
- Cross-camera deduplication: active signatures shared across cameras for same store
- Staff detection: combined colour (low HSV brightness/saturation) and movement pattern signals
- Group entry: each bounding box treated as independent visitor

### Stage 2: Event Stream (`pipeline/emit.py`)

Events are emitted in batches of 50 via HTTP POST to the Intelligence API. Each event follows a strict schema with UUID event IDs for idempotency. Timestamps are derived from clip start time + frame offset at 15fps.

### Stage 3: Intelligence API (`app/`)

Built with FastAPI and SQLite. The API ingests events, stores them, and computes real-time metrics on query.

**Endpoints:**
- `POST /events/ingest` — batch ingestion, idempotent by event_id
- `GET /stores/{id}/metrics` — visitors, conversion rate, dwell, queue
- `GET /stores/{id}/funnel` — session-based conversion funnel
- `GET /stores/{id}/heatmap` — zone visit frequency normalised 0-100
- `GET /stores/{id}/anomalies` — queue spikes, dead zones, conversion drops
- `GET /health` — feed status per store

**Conversion rate calculation:**
Conversion is computed by correlating billing zone events with POS transactions within a 5-minute window. This avoids relying solely on camera events and uses ground truth transaction data.

**Storage:**
SQLite chosen for simplicity. In production this would be PostgreSQL with persistent volumes to support historical queries across multiple days.

### Stage 4: POS Integration

Real transaction data from `pos_data.csv` is loaded on API startup into a `pos_transactions` table. Conversion rate queries JOIN this table against camera events by timestamp proximity.

## AI-Assisted Decisions

### 1. Appearance signature design
Initially used a simple RGB histogram across the full bounding box. Claude suggested using only the torso region (top 60%) and increasing bins from 8 to 16 for finer discrimination. This reduced false re-entry matches significantly — visitor ID collisions dropped from 1 ID for all visitors to correctly distinct IDs per person.

### 2. Staff detection approach
Claude initially suggested colour-only detection (black uniforms). After examining actual footage showing black uniforms and customers also wearing black, I combined colour signal with movement pattern. The combined approach reduced false positives on customers wearing dark clothing.

### 3. Database path
Claude suggested `/tmp` for the SQLite path inside Docker for simplicity. Overrode this to `/app/store_intelligence.db` mounted via Docker volume for persistence across container restarts — a production-relevant concern even in a challenge context.