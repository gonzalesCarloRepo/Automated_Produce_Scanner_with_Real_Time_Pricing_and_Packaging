import os
import time
from datetime import datetime

import cv2
from picamera2 import Picamera2

# ==========================================
# USER SETTINGS
# ==========================================
SAVE_DIR = "/home/pi/captured_images_ver2"   # Editable save path
CAPTURE_WIDTH = 640                          # Editable width
CAPTURE_HEIGHT = 640                         # Editable height
INTERVAL_SECONDS = 3.0                       # Interval after pressing 'k'
JPEG_QUALITY = 95                            # 0 to 100
WINDOW_NAME = "Camera_Ver_2"

# ==========================================
# HELPERS
# ==========================================
def make_output_path(folder: str) -> str:
    os.makedirs(folder, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(folder, f"img_{ts}.jpg")

def draw_lines(frame, lines, x=10, y=30, dy=30):
    for line in lines:
        cv2.putText(
            frame,
            line,
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
            cv2.LINE_AA
        )
        y += dy

# ==========================================
# MAIN
# ==========================================
def main():
    picam2 = Picamera2()

    # Same main stream for preview and saving
    config = picam2.create_preview_configuration(
        main={"size": (CAPTURE_WIDTH, CAPTURE_HEIGHT), "format": "RGB888"},
        buffer_count=4
    )
    picam2.configure(config)
    picam2.start()

    time.sleep(2)  # Camera warm-up

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)

    auto_mode = False
    next_capture_time = 0.0
    last_saved_text = ""
    last_saved_until = 0.0

    print("Controls:")
    print("  k = start auto capture")
    print("  s = stop auto capture")
    print("  q = quit")

    try:
        while True:
            frame_rgb = picam2.capture_array("main")
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            preview = frame_bgr.copy()
            now = time.time()

            lines = [
                f"Resolution: {CAPTURE_WIDTH} x {CAPTURE_HEIGHT}",
                f"Interval: {INTERVAL_SECONDS:.1f} sec",
                "Press 'k' start | 's' stop | 'q' quit"
            ]

            if auto_mode:
                remaining = max(0.0, next_capture_time - now)
                lines.append("AUTO CAPTURE: ON")
                lines.append(f"Next capture in: {remaining:.1f} sec")

                if now >= next_capture_time:
                    out_path = make_output_path(SAVE_DIR)
                    cv2.imwrite(
                        out_path,
                        frame_bgr,
                        [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                    )
                    last_saved_text = f"Saved: {out_path}"
                    last_saved_until = now + 2.0
                    next_capture_time = now + INTERVAL_SECONDS
            else:
                lines.append("AUTO CAPTURE: OFF")

            if now < last_saved_until:
                lines.append(last_saved_text)

            draw_lines(preview, lines)
            cv2.imshow(WINDOW_NAME, preview)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("k") and not auto_mode:
                auto_mode = True
                next_capture_time = time.time() + INTERVAL_SECONDS
            elif key == ord("s"):
                auto_mode = False
            elif key == ord("q"):
                break

    finally:
        cv2.destroyAllWindows()
        picam2.stop()
        picam2.close()

if __name__ == "__main__":
    main()