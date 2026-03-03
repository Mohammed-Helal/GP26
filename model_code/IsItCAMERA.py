import cv2
print("Searching for available cameras...")
for i in range(10):  # Check indices 0-9
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        ret, frame = cap.read()
        if ret:
            print(f"Camera {i}: Working - Resolution {frame.shape[1]}x{frame.shape[0]}")
        else:
            print(f"Camera {i}: Detected but can't read frames")
        cap.release()
    else:
        print(f"Camera {i}: Not available")
