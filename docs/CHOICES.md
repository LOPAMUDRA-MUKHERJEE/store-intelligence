# CHOICES.md — Key Engineering Decisions

## Decision 1: Detection Model — YOLOv8n

**Options considered:**
- YOLOv8n (nano) — fastest, smallest, CPU-friendly
- YOLOv8m (medium) — more accurate, 3x slower
- RT-DETR — transformer-based, higher accuracy, requires GPU
- MediaPipe — lightweight but limited tracking support

**What AI suggested:**
Claude suggested starting with YOLOv8n for CPU compatibility and speed, noting that for a 2-minute clip the accuracy trade-off is acceptable. It also suggested RT-DETR as a production upgrade path.

**What I chose and why:**
YOLOv8n. The challenge footage is 1080p at 15fps — processing every 3rd frame with YOLOv8n gives acceptable detection rates without requiring GPU. The evaluation framework explicitly states detection doesn't need to be perfect — handling edge cases and confidence calibration matters more than raw accuracy. YOLOv8n with ByteTrack tracking gave consistent multi-person detection across all camera angles.

**Trade-off acknowledged:**
A medium or large model would catch more partial occlusions. In production with GPU infrastructure, YOLOv8m would be the minimum.

---

## Decision 2: Event Schema Design

**Options considered:**
- Flat schema — all fields at top level, simple but inflexible
- Nested schema with metadata — matches the challenge spec exactly
- Event sourcing pattern — immutable log, more complex

**What AI suggested:**
Claude suggested following the challenge spec schema exactly, with a metadata object for optional fields like queue_depth and sku_zone. It also suggested using Pydantic for validation to catch schema violations at ingestion time.

**What I chose and why:**
Nested schema with Pydantic validation. The metadata object keeps optional fields clean without polluting the top-level schema. Pydantic gives automatic validation and clear error messages when events fail schema checks. UUID v4 event IDs ensure global uniqueness and enable idempotent ingestion — the same event batch can be POSTed twice safely.

**Trade-off acknowledged:**
A flat schema would be simpler to query in SQL. The nested metadata means we flatten it on ingestion into the database table.

---

## Decision 3: Conversion Rate Calculation

**Options considered:**
- Camera-only — count visitors who reached billing zone
- POS-only — count transactions, assume each is one unique visitor
- Hybrid correlation — match billing zone events to POS transactions by time window

**What AI suggested:**
Claude initially suggested camera-only using BILLING_QUEUE_JOIN events. After examining the actual footage and POS data, it revised to hybrid correlation — joining billing zone camera events with POS transactions within a 5-minute window.

**What I chose and why:**
Hybrid POS correlation. Camera-only is unreliable because staff at the billing counter get counted as converted visitors. POS-only is unreliable because one transaction could represent multiple people. The 5-minute correlation window balances accuracy with the reality that billing transactions take 1-5 minutes to complete. This approach uses ground truth transaction data while still requiring camera evidence of the visitor being present.

**Where I disagreed with AI:**
Claude initially suggested using SQLite in /tmp for simplicity. I overrode this to mount the database file via Docker volume so data persists across container restarts — a basic production requirement even in a challenge context. Claude also initially suggested camera-only conversion tracking using BILLING_QUEUE_JOIN events. After examining the actual footage and realising staff were being counted as converted visitors, I pushed for POS correlation as the more accurate approach.
