import os
import time
from datetime import datetime

import cv2
from picamera2 import Picamera2

# ==========================================
# USER SETTINGS
# ==========================================
SAVE_DIR = "/home/jekaca/camera/manual"   # Editable save path
CAPTURE_WIDTH = 700                          # Editable width
CAPTURE_HEIGHT = 640                         # Editable height
DELAY_SECONDS = 3.0                          # Delay after pressing 'k'
JPEG_QUALITY = 95                            # 0 to 100
WINDOW_NAME = "Camera_Ver_1"

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

    # One main stream only, so preview and saved image come from the same stream.
    config = picam2.create_preview_configuration(
        main={"size": (CAPTURE_WIDTH, CAPTURE_HEIGHT), "format": "RGB888"},
        buffer_count=4
    )
    picam2.configure(config)
    picam2.start()

    time.sleep(2)  # Camera warm-up

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)

    capture_pending = False
    capture_time = 0.0
    last_saved_text = ""
    last_saved_until = 0.0

    print("Controls:")
    print("  k = start delayed capture")
    print("  q = quit")

    try:
        while True:
            # Capture exactly the frame being used for this preview cycle
            frame_rgb = picam2.capture_array("main")
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            preview = frame_bgr.copy()
            now = time.time()

            lines = [
                f"Resolution: {CAPTURE_WIDTH} x {CAPTURE_HEIGHT}",
                f"Delay: {DELAY_SECONDS:.1f} sec",
                "Press 'k' to capture | 'q' to quit"
            ]

            if capture_pending:
                remaining = max(0.0, capture_time - now)
                lines.append(f"Capturing in: {remaining:.1f} sec")

                if now >= capture_time:
                    out_path = make_output_path(SAVE_DIR)
                    cv2.imwrite(
                        out_path,
                        frame_bgr,
                        [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                    )
                    last_saved_text = f"Saved: {out_path}"
                    last_saved_until = now + 2.5
                    capture_pending = False

            if now < last_saved_until:
                lines.append(last_saved_text)

            draw_lines(preview, lines)
            cv2.imshow(WINDOW_NAME, preview)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("k") and not capture_pending:
                capture_pending = True
                capture_time = time.time() + DELAY_SECONDS
            elif key == ord("q"):
                break

    finally:
        cv2.destroyAllWindows()
        picam2.stop()
        picam2.close()

if __name__ == "__main__":
    main()