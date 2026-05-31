import numpy as np
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import cv2


class VisitorTracker:
    def __init__(self, reentry_window_seconds=300, cross_camera_window_seconds=300):
        # Active tracks: (store_id, track_id) -> visitor info
        self.active_tracks = {}
        # Exited visitors: store_id -> list of {signature, visitor_id, exit_time}
        self.exited_visitors = defaultdict(list)
        # Active signatures across cameras: store_id -> {signature -> visitor_id}
        self.active_signatures = defaultdict(dict)
        # Re-entry window
        self.reentry_window = reentry_window_seconds
        # Cross camera window
        self.cross_camera_window = cross_camera_window_seconds
        # Session counter per store
        self.session_counter = defaultdict(int)
        # Track zone visit times for staff detection
        self.zone_visit_times = defaultdict(list)
        # Track continuous billing zone presence: track_key -> first_seen_timestamp
        self.billing_zone_entry = {}

    def generate_visitor_id(self, store_id: str) -> str:
        self.session_counter[store_id] += 1
        raw = f"{store_id}_{self.session_counter[store_id]}"
        short = hashlib.md5(raw.encode()).hexdigest()[:6]
        return f"VIS_{short}"

    def get_appearance_signature(self, bbox: list, frame: np.ndarray) -> str:
        x1, y1, x2, y2 = map(int, bbox)
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return "unknown"

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return "unknown"

        # Use top 60% of crop (torso) for better signature
        torso_h = int(crop.shape[0] * 0.6)
        torso = crop[:torso_h]

        hist = np.histogram(torso.reshape(-1, 3), bins=16, range=(0, 256))[0]
        hist = hist / (hist.sum() + 1e-6)
        sig = "_".join([f"{v:.2f}" for v in hist])
        return sig
    
    
    def detect_staff(self, bbox: list, frame: np.ndarray, track_id: int, store_id: str, timestamp: datetime) -> tuple:
        """
        Detect staff based on:
        1. Movement pattern — staff move rapidly and frequently
        2. Black uniform — low brightness AND low saturation in HSV
        Both signals combined for better accuracy.
        Returns (is_staff, confidence)
        """
        x1, y1, x2, y2 = map(int, bbox)
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        # Movement pattern signal
        key = f"{store_id}_{track_id}"
        self.zone_visit_times[key].append(timestamp)
        visits = self.zone_visit_times[key]

        movement_score = 0.0
        if len(visits) >= 5:
            time_span = (visits[-1] - visits[0]).total_seconds()
            if time_span > 0:
                movement_rate = len(visits) / time_span
                if movement_rate > 0.5 and len(visits) > 10:
                    movement_score = 0.8
                elif movement_rate > 0.3 and len(visits) > 20:
                    movement_score = 0.6

        # Color signal — black uniform
        color_score = 0.0
        if x2 > x1 and y2 > y1:
            crop = frame[y1:y2, x1:x2]
            if crop.size > 0:
                # Use torso only (top 60%)
                torso_h = int(crop.shape[0] * 0.6)
                torso = crop[:torso_h]
                if torso.size > 0:
                    hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
                    value_channel = hsv[:, :, 2]
                    saturation_channel = hsv[:, :, 1]
                    dark_ratio = np.sum(
                        (value_channel < 60) & (saturation_channel < 60)
                    ) / (value_channel.size + 1e-6)

                    if dark_ratio > 0.5:
                        color_score = 0.7
                    elif dark_ratio > 0.35:
                        color_score = 0.4

        # Combine both signals
        # Both agree = high confidence
        # Only one signal = moderate confidence
        if movement_score > 0.5 and color_score > 0.5:
            return True, 0.85
        elif movement_score > 0.5:
            return True, movement_score
        elif color_score > 0.6:
            # Color alone only flags if very dark — avoids customer in black issue
            return True, color_score * 0.7
        
        return False, 0.5

    # def detect_staff(self, bbox: list, frame: np.ndarray, track_id: int, store_id: str, timestamp: datetime) -> tuple:
    #     """
    #     Detect staff based on:
    #     1. Black uniform (low brightness in HSV)
    #     2. Rapid movement across zones
    #     Returns (is_staff, confidence)
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

    #     # Check for black uniform — low brightness
    #     hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    #     # Black = low Value channel
    #     value_channel = hsv[:, :, 2]
    #     dark_ratio = np.sum(value_channel < 50) / (value_channel.size + 1e-6)

    #     # Check for rapid zone movement
    #     key = f"{store_id}_{track_id}"
    #     self.zone_visit_times[key].append(timestamp)
    #     visits = self.zone_visit_times[key]

    #     rapid_movement = False
    #     if len(visits) >= 3:
    #         time_span = (visits[-1] - visits[0]).total_seconds()
    #         if time_span < 60 and len(visits) >= 3:
    #             rapid_movement = True

    #     if dark_ratio > 0.4 and rapid_movement:
    #         return True, 0.85
    #     elif dark_ratio > 0.5:
    #         return True, 0.7
    #     elif rapid_movement:
    #         return True, 0.6

    #     return False, 0.5

    def compare_signatures(self, sig1: str, sig2: str) -> float:
        if sig1 == "unknown" or sig2 == "unknown":
            return 0.0
        try:
            v1 = np.array([float(x) for x in sig1.split("_")])
            v2 = np.array([float(x) for x in sig2.split("_")])
            dot = np.dot(v1, v2)
            norm = np.linalg.norm(v1) * np.linalg.norm(v2)
            return float(dot / (norm + 1e-6))
        except:
            return 0.0

    def process_track(
        self,
        track_id: int,
        bbox: list,
        frame: np.ndarray,
        store_id: str,
        timestamp: datetime,
        camera_id: str = ""
    ) -> tuple:
        """
        Returns (visitor_id, is_reentry, is_staff)
        """
        track_key = f"{store_id}_{track_id}_{camera_id}"

        # Already tracking this track
        if track_key in self.active_tracks:
            info = self.active_tracks[track_key]
            is_staff, _ = self.detect_staff(bbox, frame, track_id, store_id, timestamp)
            return info["visitor_id"], False, is_staff

        signature = self.get_appearance_signature(bbox, frame)
        is_staff, staff_conf = self.detect_staff(bbox, frame, track_id, store_id, timestamp)

        # 1. Cross-camera deduplication
        # Check if this person is already active from another camera
        if signature != "unknown":
            for existing_sig, existing_visitor_id in self.active_signatures[store_id].items():
                score = self.compare_signatures(signature, existing_sig)
                # if score > 0.85:
                if score > 0.92:
                    # Same person already tracked from another camera
                    self.active_tracks[track_key] = {
                        "visitor_id": existing_visitor_id,
                        "store_id": store_id,
                        "signature": signature,
                        "first_seen": timestamp,
                        "is_staff": is_staff,
                        "session_seq": 0,
                        "camera_id": camera_id
                    }
                    return existing_visitor_id, False, is_staff

        # 2. Re-entry check
        best_match = None
        best_score = 0.0

        for exited_info in self.exited_visitors[store_id]:
            time_since_exit = (timestamp - exited_info["exit_time"]).total_seconds()
            if time_since_exit > self.reentry_window:
                continue
            # Minimum 60 seconds before considering re-entry
            if time_since_exit < 60:
                continue
            score = self.compare_signatures(signature, exited_info["signature"])
            # if score > 0.85 and score > best_score:
            if score > 0.90 and score > best_score:
                best_score = score
                best_match = exited_info

        if best_match:
            visitor_id = best_match["visitor_id"]
            is_reentry = True
        else:
            visitor_id = self.generate_visitor_id(store_id)
            is_reentry = False

        self.active_tracks[track_key] = {
            "visitor_id": visitor_id,
            "store_id": store_id,
            "signature": signature,
            "first_seen": timestamp,
            "is_staff": is_staff,
            "session_seq": 0,
            "camera_id": camera_id
        }

        # Register in active signatures for cross-camera dedup
        if signature != "unknown":
            self.active_signatures[store_id][signature] = visitor_id

        return visitor_id, is_reentry, is_staff

    def close_track(self, track_id: int, camera_id: str, store_id: str, timestamp: datetime):
        track_key = f"{store_id}_{track_id}_{camera_id}"
        if track_key not in self.active_tracks:
            return

        info = self.active_tracks.pop(track_key)

        # Remove from active signatures
        if info["signature"] in self.active_signatures[store_id]:
            del self.active_signatures[store_id][info["signature"]]

        # Add to exited
        self.exited_visitors[store_id].append({
            "visitor_id": info["visitor_id"],
            "signature": info["signature"],
            "exit_time": timestamp
        })

    def increment_seq(self, track_id: int, camera_id: str, store_id: str) -> int:
        track_key = f"{store_id}_{track_id}_{camera_id}"
        if track_key in self.active_tracks:
            self.active_tracks[track_key]["session_seq"] += 1
            return self.active_tracks[track_key]["session_seq"]
        return 0




# import numpy as np
# from collections import defaultdict
# from datetime import datetime, timezone
# import hashlib


# class VisitorTracker:
#     def __init__(self, reentry_window_seconds=300):
#         # Active tracks: track_id -> visitor info
#         self.active_tracks = {}
#         # Exited visitors: appearance_signature -> visitor_id
#         self.exited_visitors = {}
#         # Re-entry window in seconds
#         self.reentry_window = reentry_window_seconds
#         # Session counter per store
#         self.session_counter = defaultdict(int)

#     def generate_visitor_id(self, store_id: str) -> str:
#         self.session_counter[store_id] += 1
#         raw = f"{store_id}_{self.session_counter[store_id]}"
#         short = hashlib.md5(raw.encode()).hexdigest()[:6]
#         return f"VIS_{short}"

#     def get_appearance_signature(self, bbox: list, frame: np.ndarray) -> str:
#         x1, y1, x2, y2 = map(int, bbox)
#         h, w = frame.shape[:2]
#         x1, y1 = max(0, x1), max(0, y1)
#         x2, y2 = min(w, x2), min(h, y2)

#         if x2 <= x1 or y2 <= y1:
#             return "unknown"

#         crop = frame[y1:y2, x1:x2]
#         if crop.size == 0:
#             return "unknown"

#         # Simple colour histogram as appearance signature
#         hist = np.histogram(crop.reshape(-1, 3), bins=8, range=(0, 256))[0]
#         hist = hist / (hist.sum() + 1e-6)
#         sig = "_".join([f"{v:.2f}" for v in hist])
#         return sig

#     def compare_signatures(self, sig1: str, sig2: str) -> float:
#         if sig1 == "unknown" or sig2 == "unknown":
#             return 0.0
#         v1 = np.array([float(x) for x in sig1.split("_")])
#         v2 = np.array([float(x) for x in sig2.split("_")])
#         # Cosine similarity
#         dot = np.dot(v1, v2)
#         norm = np.linalg.norm(v1) * np.linalg.norm(v2)
#         return dot / (norm + 1e-6)

#     def process_track(
#         self,
#         track_id: int,
#         bbox: list,
#         frame: np.ndarray,
#         store_id: str,
#         timestamp: datetime,
#         is_staff: bool = False
#     ) -> tuple:
#         """
#         Returns (visitor_id, is_reentry)
#         """
#         # Already tracking this track_id
#         if track_id in self.active_tracks:
#             return self.active_tracks[track_id]["visitor_id"], False

#         # New track — check if it matches an exited visitor
#         signature = self.get_appearance_signature(bbox, frame)

#         best_match = None
#         best_score = 0.0

#         for exited_sig, exited_info in self.exited_visitors.items():
#             # Only check recent exits
#             time_since_exit = (timestamp - exited_info["exit_time"]).total_seconds()
#             if time_since_exit > self.reentry_window:
#                 continue

#             score = self.compare_signatures(signature, exited_sig)
#             if score > 0.85 and score > best_score:
#                 best_score = score
#                 best_match = exited_info

#         if best_match:
#             visitor_id = best_match["visitor_id"]
#             is_reentry = True
#         else:
#             visitor_id = self.generate_visitor_id(store_id)
#             is_reentry = False

#         self.active_tracks[track_id] = {
#             "visitor_id": visitor_id,
#             "store_id": store_id,
#             "signature": signature,
#             "first_seen": timestamp,
#             "is_staff": is_staff,
#             "session_seq": 0
#         }

#         return visitor_id, is_reentry

#     def close_track(self, track_id: int, timestamp: datetime):
#         if track_id not in self.active_tracks:
#             return
#         info = self.active_tracks.pop(track_id)
#         self.exited_visitors[info["signature"]] = {
#             "visitor_id": info["visitor_id"],
#             "exit_time": timestamp
#         }

#     def increment_seq(self, track_id: int) -> int:
#         if track_id in self.active_tracks:
#             self.active_tracks[track_id]["session_seq"] += 1
#             return self.active_tracks[track_id]["session_seq"]
#         return 0