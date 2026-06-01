import cv2
import numpy as np
from ultralytics import YOLO
from datetime import datetime, timezone, timedelta
import argparse
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.tracker import VisitorTracker
from pipeline.emit import make_event, emit_events, format_timestamp


def load_store_layout(layout_path: str) -> dict:
    with open(layout_path, "r") as f:
        return json.load(f)


def is_crossing_threshold(prev_y: float, curr_y: float, threshold_y: float) -> str:
    if prev_y > threshold_y and curr_y <= threshold_y:
        return "ENTRY"
    elif prev_y <= threshold_y and curr_y > threshold_y:
        return "EXIT"
    return None


def get_zone_for_bbox(bbox: list, zones: dict, camera_id: str):
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    for zone_id, zone_info in zones.items():
        if zone_info.get("camera", "") not in camera_id:
            continue
        x1, y1, x2, y2 = zone_info["bbox"]
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            return zone_id, zone_info.get("sku_zone")
    return None, None


def process_clip(
    video_path: str,
    store_id: str,
    camera_id: str,
    camera_type: str,
    clip_start_time: datetime,
    zones: dict,
    entry_threshold_y: float = 0.75,
    tracker: VisitorTracker = None
):
    model = YOLO("yolov8n.pt")

    if tracker is None:
        tracker = VisitorTracker()

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    frame_count = 0

    prev_positions = {}
    zone_entry_times = {}
    zone_dwell_emitted = {}
    billing_presence = {}
    entry_cooldown = {}
    all_events = []
    batch_size = 50

    print(f"\nProcessing {video_path} — {store_id} {camera_id} ({camera_type})")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1

        if frame_count % 3 != 0:
            continue

        timestamp = format_timestamp(clip_start_time, frame_count, fps)

        results = model.track(frame, persist=True, classes=[0], verbose=False)

        if results[0].boxes is None or results[0].boxes.id is None:
            continue

        boxes = results[0].boxes.xyxy.cpu().numpy()
        track_ids = results[0].boxes.id.cpu().numpy().astype(int)
        confidences = results[0].boxes.conf.cpu().numpy()

        current_track_ids = set(track_ids)

        for key in list(tracker.active_tracks.keys()):
            parts = key.split("_")
            if len(parts) >= 3:
                try:
                    tid = int(parts[1])
                    if tid not in current_track_ids and parts[0] == store_id:
                        tracker.close_track(tid, camera_id, store_id, timestamp)
                except:
                    pass

        for box, track_id, conf in zip(boxes, track_ids, confidences):
            visitor_id, is_reentry, is_staff = tracker.process_track(
                track_id, box, frame, store_id, timestamp, camera_id
            )

            seq = tracker.increment_seq(track_id, camera_id, store_id)
            frame_h = frame.shape[0]
            threshold_y = frame_h * entry_threshold_y

            # ENTRY/EXIT logic
            if camera_type == "ENTRY":
                curr_cy = (box[1] + box[3]) / 2

                if track_id in prev_positions:
                    prev_cy = (prev_positions[track_id][1] + prev_positions[track_id][3]) / 2
                    crossing = is_crossing_threshold(prev_cy, curr_cy, threshold_y)

                    if crossing == "ENTRY" and float(conf) >= 0.3:
                        last_entry = entry_cooldown.get(track_id)
                        cooldown_ok = (
                            last_entry is None or
                            (timestamp - last_entry).total_seconds() > 10
                        )
                        if cooldown_ok:
                            event_type = "REENTRY" if is_reentry else "ENTRY"
                            all_events.append(make_event(
                                store_id=store_id,
                                camera_id=camera_id,
                                visitor_id=visitor_id,
                                event_type=event_type,
                                timestamp=timestamp,
                                is_staff=is_staff,
                                confidence=float(conf),
                                session_seq=seq
                            ))
                            entry_cooldown[track_id] = timestamp
                            print(f"  {event_type}: visitor={visitor_id} staff={is_staff} conf={conf:.2f}")

                    elif crossing == "EXIT" and float(conf) >= 0.3:
                        tracker.close_track(track_id, camera_id, store_id, timestamp)
                        all_events.append(make_event(
                            store_id=store_id,
                            camera_id=camera_id,
                            visitor_id=visitor_id,
                            event_type="EXIT",
                            timestamp=timestamp,
                            is_staff=is_staff,
                            confidence=float(conf),
                            session_seq=seq
                        ))
                        print(f"  EXIT: visitor={visitor_id} staff={is_staff}")

                else:
                    # New track appearing inside threshold = group entry or missed crossing
                    # if curr_cy < threshold_y * 0.85 and float(conf) >= 0.3:
                    #     last_entry = entry_cooldown.get(track_id)
                    #     cooldown_ok = (
                    #         last_entry is None or
                    #         (timestamp - last_entry).total_seconds() > 10
                    #     )
                    #     if cooldown_ok:
                    #         event_type = "REENTRY" if is_reentry else "ENTRY"
                    #         all_events.append(make_event(
                    #             store_id=store_id,
                    #             camera_id=camera_id,
                    #             visitor_id=visitor_id,
                    #             event_type=event_type,
                    #             timestamp=timestamp,
                    #             is_staff=is_staff,
                    #             confidence=float(conf),
                    #             session_seq=seq
                    #         ))
                    #         entry_cooldown[track_id] = timestamp
                    #         print(f"  {event_type} (appeared inside): visitor={visitor_id} staff={is_staff} conf={conf:.2f}")
                    pass
                            # Group entry detection disabled for short clips
                            # New track appearing inside = too noisy at door boundary
                            # Re-enable for longer clips with clearer entry zones

            # ZONE logic for floor and billing cameras
            if camera_type in ["FLOOR", "BILLING"]:
                zone_id, sku_zone = get_zone_for_bbox(box, zones, camera_id)

                if zone_id:
                    track_zone_key = f"{track_id}_{zone_id}"

                    if track_id not in zone_entry_times:
                        zone_entry_times[track_id] = {}

                    # Stationary behind counter = staff (billing camera only)
                    if camera_type == "BILLING":
                        if track_id not in billing_presence:
                            billing_presence[track_id] = timestamp
                        else:
                            seconds_in_billing = (timestamp - billing_presence[track_id]).total_seconds()
                            if seconds_in_billing > 60 and not is_staff:
                                is_staff = True
                                print(f"  Staff detected (stationary): visitor={visitor_id} seconds={int(seconds_in_billing)}")

                    if zone_id not in zone_entry_times[track_id]:
                        zone_entry_times[track_id][zone_id] = timestamp
                        all_events.append(make_event(
                            store_id=store_id,
                            camera_id=camera_id,
                            visitor_id=visitor_id,
                            event_type="ZONE_ENTER",
                            timestamp=timestamp,
                            zone_id=zone_id,
                            is_staff=is_staff,
                            confidence=float(conf),
                            sku_zone=sku_zone,
                            session_seq=seq
                        ))

                        if camera_type == "BILLING":
                            billing_visitors = [
                                v for k, v in tracker.active_tracks.items()
                                if k.endswith(camera_id) and not v["is_staff"]
                            ]
                            queue_depth = len(billing_visitors)
                            if queue_depth > 0:
                                all_events.append(make_event(
                                    store_id=store_id,
                                    camera_id=camera_id,
                                    visitor_id=visitor_id,
                                    event_type="BILLING_QUEUE_JOIN",
                                    timestamp=timestamp,
                                    zone_id=zone_id,
                                    is_staff=is_staff,
                                    confidence=float(conf),
                                    queue_depth=queue_depth,
                                    sku_zone=sku_zone,
                                    session_seq=seq
                                ))

                    else:
                        dwell_ms = int((timestamp - zone_entry_times[track_id][zone_id]).total_seconds() * 1000)
                        last_dwell = zone_dwell_emitted.get(track_zone_key, 0)

                        if dwell_ms - last_dwell >= 5000:
                            all_events.append(make_event(
                                store_id=store_id,
                                camera_id=camera_id,
                                visitor_id=visitor_id,
                                event_type="ZONE_DWELL",
                                timestamp=timestamp,
                                zone_id=zone_id,
                                dwell_ms=dwell_ms,
                                is_staff=is_staff,
                                confidence=float(conf),
                                sku_zone=sku_zone,
                                session_seq=seq
                            ))
                            zone_dwell_emitted[track_zone_key] = dwell_ms

            prev_positions[track_id] = box

        if len(all_events) >= batch_size:
            result = emit_events(all_events)
            print(f"  Batch emitted: {len(all_events)} events — {result}")
            all_events = []

    if all_events:
        result = emit_events(all_events)
        print(f"  Final batch: {len(all_events)} events — {result}")

    cap.release()
    print(f"Done: {video_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--camera-type", required=True, choices=["ENTRY", "FLOOR", "BILLING"])
    parser.add_argument("--layout", required=True)
    parser.add_argument("--clip-start", required=True)
    parser.add_argument("--threshold", type=float, default=0.75)
    args = parser.parse_args()

    layout = load_store_layout(args.layout)
    store_zones = layout.get(args.store_id, {}).get("zones", {})
    clip_start = datetime.fromisoformat(args.clip_start)

    process_clip(
        video_path=args.video,
        store_id=args.store_id,
        camera_id=args.camera_id,
        camera_type=args.camera_type,
        clip_start_time=clip_start,
        zones=store_zones,
        entry_threshold_y=args.threshold
    )





# import cv2
# import numpy as np
# from ultralytics import YOLO
# from datetime import datetime, timezone
# import argparse
# import json
# import os
# import sys

# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# from pipeline.tracker import VisitorTracker
# from pipeline.emit import make_event, emit_events, format_timestamp


# # Zone definitions — will be loaded from store_layout.json
# def load_store_layout(layout_path: str) -> dict:
#     with open(layout_path, "r") as f:
#         return json.load(f)


# def is_crossing_threshold(prev_y: float, curr_y: float, threshold_y: float) -> str:
#     """Determine entry or exit based on vertical movement across threshold."""
#     if prev_y < threshold_y and curr_y >= threshold_y:
#         return "ENTRY"
#     elif prev_y >= threshold_y and curr_y < threshold_y:
#         return "EXIT"
#     return None


# def get_zone_for_bbox(bbox: list, zones: dict) -> str:
#     cx = (bbox[0] + bbox[2]) / 2
#     cy = (bbox[1] + bbox[3]) / 2
#     for zone_id, zone_info in zones.items():
#         x1, y1, x2, y2 = zone_info["bbox"]
#         if x1 <= cx <= x2 and y1 <= cy <= y2:
#             return zone_id
#     return None


# def detect_staff(bbox: list, frame: np.ndarray) -> tuple:
#     """
#     Simple staff detection based on clothing colour.
#     Returns (is_staff, confidence)
#     Staff typically wear uniforms — adjust colour range for actual footage.
#     """
#     x1, y1, x2, y2 = map(int, bbox)
#     h, w = frame.shape[:2]
#     x1, y1 = max(0, x1), max(0, y1)
#     x2, y2 = min(w, x2), min(h, y2)

#     if x2 <= x1 or y2 <= y1:
#         return False, 0.5

#     crop = frame[y1:y2, x1:x2]
#     if crop.size == 0:
#         return False, 0.5

#     # Convert to HSV for colour detection
#     hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

#     # Example: staff wear blue uniforms
#     # Adjust these ranges based on actual store uniform colour
#     lower_blue = np.array([100, 50, 50])
#     upper_blue = np.array([130, 255, 255])
#     mask = cv2.inRange(hsv, lower_blue, upper_blue)
#     blue_ratio = mask.sum() / (mask.size + 1e-6) * 255

#     if blue_ratio > 0.3:
#         return True, min(0.95, blue_ratio)

#     return False, 0.5


# def process_clip(
#     video_path: str,
#     store_id: str,
#     camera_id: str,
#     camera_type: str,
#     clip_start_time: datetime,
#     zones: dict,
#     entry_threshold_y: float = 0.75
# ):
#     model = YOLO("yolov8n.pt")
#     tracker = VisitorTracker()

#     cap = cv2.VideoCapture(video_path)
#     fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
#     frame_count = 0

#     # Track state
#     prev_positions = {}
#     zone_entry_times = {}
#     zone_dwell_emitted = {}
#     all_events = []
#     batch_size = 50

#     print(f"Processing {video_path} — {store_id} {camera_id}")

#     while cap.isOpened():
#         ret, frame = cap.read()
#         if not ret:
#             break

#         frame_count += 1

#         # Process every 3rd frame for speed
#         if frame_count % 3 != 0:
#             continue

#         timestamp = format_timestamp(clip_start_time, frame_count, fps)

#         # Run YOLO tracking
#         results = model.track(frame, persist=True, classes=[0], verbose=False)

#         if results[0].boxes is None or results[0].boxes.id is None:
#             continue

#         boxes = results[0].boxes.xyxy.cpu().numpy()
#         track_ids = results[0].boxes.id.cpu().numpy().astype(int)
#         confidences = results[0].boxes.conf.cpu().numpy()

#         current_track_ids = set()

#         for box, track_id, conf in zip(boxes, track_ids, confidences):
#             current_track_ids.add(track_id)

#             is_staff, staff_conf = detect_staff(box, frame)

#             visitor_id, is_reentry = tracker.process_track(
#                 track_id, box, frame, store_id, timestamp, is_staff
#             )

#             seq = tracker.increment_seq(track_id)
#             frame_h = frame.shape[0]
#             threshold_y = frame_h * entry_threshold_y

#             # Entry/Exit detection (entry camera only)
#             if camera_type == "ENTRY" and track_id in prev_positions:
#                 prev_cy = (prev_positions[track_id][1] + prev_positions[track_id][3]) / 2
#                 curr_cy = (box[1] + box[3]) / 2
#                 crossing = is_crossing_threshold(prev_cy, curr_cy, threshold_y)

#                 if crossing == "ENTRY" and not is_reentry:
#                     all_events.append(make_event(
#                         store_id=store_id,
#                         camera_id=camera_id,
#                         visitor_id=visitor_id,
#                         event_type="ENTRY",
#                         timestamp=timestamp,
#                         is_staff=is_staff,
#                         confidence=float(conf),
#                         session_seq=seq
#                     ))
#                 elif crossing == "ENTRY" and is_reentry:
#                     all_events.append(make_event(
#                         store_id=store_id,
#                         camera_id=camera_id,
#                         visitor_id=visitor_id,
#                         event_type="REENTRY",
#                         timestamp=timestamp,
#                         is_staff=is_staff,
#                         confidence=float(conf),
#                         session_seq=seq
#                     ))
#                 elif crossing == "EXIT":
#                     tracker.close_track(track_id, timestamp)
#                     all_events.append(make_event(
#                         store_id=store_id,
#                         camera_id=camera_id,
#                         visitor_id=visitor_id,
#                         event_type="EXIT",
#                         timestamp=timestamp,
#                         is_staff=is_staff,
#                         confidence=float(conf),
#                         session_seq=seq
#                     ))

#             # Zone detection (floor camera)
#             if camera_type == "FLOOR" and zones:
#                 zone_id = get_zone_for_bbox(box, zones)

#                 if zone_id:
#                     if track_id not in zone_entry_times:
#                         zone_entry_times[track_id] = {}

#                     if zone_id not in zone_entry_times[track_id]:
#                         zone_entry_times[track_id][zone_id] = timestamp
#                         all_events.append(make_event(
#                             store_id=store_id,
#                             camera_id=camera_id,
#                             visitor_id=visitor_id,
#                             event_type="ZONE_ENTER",
#                             timestamp=timestamp,
#                             zone_id=zone_id,
#                             is_staff=is_staff,
#                             confidence=float(conf),
#                             session_seq=seq
#                         ))
#                     else:
#                         dwell_ms = int((timestamp - zone_entry_times[track_id][zone_id]).total_seconds() * 1000)
#                         dwell_key = f"{track_id}_{zone_id}"

#                         last_dwell = zone_dwell_emitted.get(dwell_key, 0)
#                         if dwell_ms - last_dwell >= 30000:
#                             all_events.append(make_event(
#                                 store_id=store_id,
#                                 camera_id=camera_id,
#                                 visitor_id=visitor_id,
#                                 event_type="ZONE_DWELL",
#                                 timestamp=timestamp,
#                                 zone_id=zone_id,
#                                 dwell_ms=dwell_ms,
#                                 is_staff=is_staff,
#                                 confidence=float(conf),
#                                 session_seq=seq
#                             ))
#                             zone_dwell_emitted[dwell_key] = dwell_ms

#             prev_positions[track_id] = box

#         # Emit in batches
#         if len(all_events) >= batch_size:
#             result = emit_events(all_events)
#             print(f"Frame {frame_count}: emitted {len(all_events)} events — {result}")
#             all_events = []

#     # Emit remaining events
#     if all_events:
#         emit_events(all_events)

#     cap.release()
#     print(f"Done processing {video_path}")


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser()
#     parser.add_argument("--video", required=True)
#     parser.add_argument("--store-id", required=True)
#     parser.add_argument("--camera-id", required=True)
#     parser.add_argument("--camera-type", required=True, choices=["ENTRY", "FLOOR", "BILLING"])
#     parser.add_argument("--layout", required=True)
#     parser.add_argument("--clip-start", required=True, help="ISO datetime e.g. 2026-03-03T10:00:00")
#     parser.add_argument("--threshold", type=float, default=0.75)
#     args = parser.parse_args()

#     layout = load_store_layout(args.layout)
#     store_zones = layout.get(args.store_id, {}).get("zones", {})

#     clip_start = datetime.fromisoformat(args.clip_start)

#     process_clip(
#         video_path=args.video,
#         store_id=args.store_id,
#         camera_id=args.camera_id,
#         camera_type=args.camera_type,
#         clip_start_time=clip_start,
#         zones=store_zones
#     )