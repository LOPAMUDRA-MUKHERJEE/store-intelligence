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

---

## Decision 4: Group Entry Detection — Implement but Disable on CAM3

**Options considered:**
- Ignore groups entirely — treat every bounding box as an independent visitor
- Implement group detection across all cameras uniformly
- Implement group detection but gate it per camera based on reliability

**What AI suggested:**
Claude suggested detecting groups by clustering bounding boxes with IoU overlap > 0.3 at entry frames, and flagging clusters of 2+ as group entries. It suggested applying this uniformly across all entry-facing cameras.

**What I chose and why:**
Implemented group detection logic in `tracker.py` but disabled it specifically for CAM3 (entry camera). The implementation works: it clusters co-entering bounding boxes and emits a GROUP_ENTRY event with a group_size field. However, CAM3's angle places the door boundary mid-frame. People entering appear as partial bounding boxes at the top edge before fully entering — this causes IoU clustering to spuriously group people who are actually entering at different times but whose partial boxes overlap spatially.

Disabling it on CAM3 rather than deleting it was deliberate. The logic is correct; the problem is camera placement, not the algorithm. Keeping the code in place means it can be re-enabled if the camera is repositioned, or enabled for other cameras at better angles.

**Trade-off acknowledged:**
With group detection disabled, group entries are counted as individual visitors. This slightly inflates unique_visitors for group shopping trips. A better-positioned entry camera, or a depth sensor for true entry-line detection, would resolve this cleanly.

---

## Decision 5: Staff Detection — Combined Signal, Not Colour-Only

**Options considered:**
- Colour-only — flag any track with predominant black/dark uniform
- Movement-only — flag tracks stationary 60+ seconds
- Combined — require both signals simultaneously

**What AI suggested:**
Claude initially suggested colour-only detection using HSV range for black clothing. A simple threshold on the proportion of dark pixels in the bounding box crop.

**What I chose and why:**
Combined signal. After running the pipeline against the actual footage, colour-only produced false positives: multiple customers happened to be wearing dark clothing. The combined approach requires both the uniform colour signature AND a stationary period of 60+ consecutive seconds in the billing zone. This combination is behaviorally specific to staff — customers wearing black don't stand still at billing for 60 seconds unless they're transacting, and billing transaction time is short enough that it doesn't trigger the threshold.

**Trade-off acknowledged:**
A staff member actively restocking (moving around) wouldn't be filtered by movement pattern. A future improvement would train a small classifier on uniform appearance at higher resolution. For this dataset, the combined heuristic is sufficient.


