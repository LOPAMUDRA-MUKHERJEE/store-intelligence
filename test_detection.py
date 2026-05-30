# from ultralytics import YOLO
# import cv2

# model = YOLO('yolov8n.pt')
# cap = cv2.VideoCapture('CCTV footage/CAM 3.mp4')
# ret, frame = cap.read()
# results = model(frame, classes=[0], verbose=False)
# print('Detections:', len(results[0].boxes))
# print('Frame shape:', frame.shape)
# cap.release()

# from ultralytics import YOLO
# import cv2

# model = YOLO('yolov8n.pt')
# cap = cv2.VideoCapture('CCTV footage/CAM 3.mp4')

# total_detections = 0
# frames_checked = 0

# for i in range(300):
#     ret, frame = cap.read()
#     if not ret:
#         break
#     if i % 15 == 0:
#         results = model(frame, classes=[0], verbose=False)
#         count = len(results[0].boxes)
#         total_detections += count
#         frames_checked += 1
#         print(f"Frame {i}: {count} people detected")

# cap.release()
# print(f"\nTotal frames checked: {frames_checked}")
# print(f"Total detections: {total_detections}")

from ultralytics import YOLO
import cv2

model = YOLO('yolov8n.pt')
cap = cv2.VideoCapture('CCTV footage/CAM 3.mp4')

ret, frame = cap.read()
results = model(frame, classes=[0], verbose=False)

# Draw detections
for box in results[0].boxes.xyxy.cpu().numpy():
    x1, y1, x2, y2 = map(int, box)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
    cy = (y1 + y2) // 2
    print(f"Person at y-center: {cy} (frame height: {frame.shape[0]})")

# Draw threshold line at 50% height
threshold_y = frame.shape[0] // 2
cv2.line(frame, (0, threshold_y), (frame.shape[1], threshold_y), (0, 0, 255), 2)

cv2.imwrite('test_frame.jpg', frame)
print("Saved test_frame.jpg — open it to see detections")
cap.release()