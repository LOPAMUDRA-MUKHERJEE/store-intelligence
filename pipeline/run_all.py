import subprocess
import sys

clips = [
    {
        "video": "CCTV Footage/CAM 1.mp4",
        "store_id": "ST1008",
        "camera_id": "CAM1",
        "camera_type": "FLOOR",
        "clip_start": "2026-04-10T20:10:00"
    },
    {
        "video": "CCTV Footage/CAM 2.mp4",
        "store_id": "ST1008",
        "camera_id": "CAM2",
        "camera_type": "FLOOR",
        "clip_start": "2026-04-10T20:10:00"
    },
    {
        "video": "CCTV Footage/CAM 3.mp4",
        "store_id": "ST1008",
        "camera_id": "CAM3",
        "camera_type": "ENTRY",
        "clip_start": "2026-04-10T20:10:00"
    },
    {
        "video": "CCTV Footage/CAM 5.mp4",
        "store_id": "ST1008",
        "camera_id": "CAM5",
        "camera_type": "BILLING",
        "clip_start": "2026-04-10T20:10:00"
    }
]

for clip in clips:
    cmd = [
        sys.executable, "pipeline/detect.py",
        "--video", clip["video"],
        "--store-id", clip["store_id"],
        "--camera-id", clip["camera_id"],
        "--camera-type", clip["camera_type"],
        "--layout", "store_layout.json",
        "--clip-start", clip["clip_start"]
    ]
    print(f"\nRunning: {clip['camera_id']} ({clip['camera_type']})")
    subprocess.run(cmd)

print("\nAll clips processed!")