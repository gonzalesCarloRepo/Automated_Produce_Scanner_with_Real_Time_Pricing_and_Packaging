import os
import time
from datetime import datetime

import cv2
from picamera2 import Picamera2

# ==========================================
# USER SETTINGS
# ==========================================
SAVE_DIR = "/home/pi/captured_images_ver1_zoom_ui"
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 640
DELAY_SECONDS = 3.0
JPEG_QUALITY = 95

ZOOM_MIN = 1.00
ZOOM_MAX = 4.00
FINE_ZOOM_STEP = 0.02
COARSE_ZOOM_STEP = 0.10
START_ZOOM = 1.00

WINDOW_NAME = "Camera_Ver_1_Zoom_UI"

# ==========================================
# HELPERS
# ==========================================
def clamp(value, low, high):
    return max(low, min(high, value))

def make_even(n):
    n = int(n)
    return n if n % 2 == 0 else n - 1

def make_output_path(folder: str) -> str:
    os.makedirs(folder, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(folder, f"img_{ts}.jpg")

def apply_zoom(picam2, base_crop, zoom_factor):
    x0, y0, w0, h0 = base_crop

    new_w = max(64, make_even(w0 / zoom_factor))
    new_h = max(64, make_even(h0 / zoom_factor))

    new_x = make_even(x0 + (w0 - new_w) / 2)
    new_y = make_even(y0 + (h0 - new_h) / 2)

    picam2.set_controls({"ScalerCrop": [new_x, new_y, new_w, new_h]})

def draw_text_lines(frame, lines, x, y, dy=28, font_scale=0.60, color=(0, 255, 0), thickness=2):
    for line in lines:
        cv2.putText(
            frame,
            line,
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA
        )
        y += dy

def draw_filled_panel(frame, x1, y1, x2, y2, alpha=0.45):
    overlay = frame.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 0, 0), -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), 1)

def draw_zoom_bar(frame, zoom_value, zoom_min, zoom_max):
    h, w = frame.shape[:2]

    bar_x = 20
    bar_y = h - 34
    bar_w = 300
    bar_h = 14

    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (255, 255, 255), 1)

    ratio = 0.0 if zoom_max == zoom_min else (zoom_value - zoom_min) / (zoom_max - zoom_min)
    ratio = max(0.0, min(1.0, ratio))
    fill_w = int(bar_w * ratio)

    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), (0, 255, 0), -1)

    cv2.putText(
        frame,
        f"Zoom Bar: {zoom_value:.2f}x",
        (bar_x, bar_y - 8),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 255, 0),
        2,
        cv2.LINE_AA
    )

def draw_ui(frame, zoom_factor, capture_pending, remaining_time, last_saved_text):
    h, w = frame.shape[:2]

    # Left status panel
    draw_filled_panel(frame, 10, 10, 420, 180, alpha=0.40)
    left_lines = [
        "CAMERA_VER_1 : MANUAL DELAY CAPTURE",
        f"Resolution : {CAPTURE_WIDTH} x {CAPTURE_HEIGHT}",
        f"Delay      : {DELAY_SECONDS:.1f} sec",
        f"Zoom       : {zoom_factor:.2f}x",
        f"Mode       : {'WAITING TO CAPTURE' if capture_pending else 'IDLE'}",
    ]
    if capture_pending:
        left_lines.append(f"Countdown  : {remaining_time:.1f} sec")
    else:
        left_lines.append("Countdown  : -")

    if last_saved_text:
        left_lines.append(last_saved_text)

    draw_text_lines(frame, left_lines, 25, 35, dy=24, font_scale=0.58)

    # Right controls panel
    draw_filled_panel(frame, w - 360, 10, w - 10, 290, alpha=0.40)
    right_lines = [
        "KEYBOARD CONTROLS",
        "k  = start delayed capture",
        "z  = zoom out fine",
        "x  = zoom in fine",
        "a  = zoom out coarse",
        "d  = zoom in coarse",
        "0  = reset zoom to 1.00x",
        "q  = quit",
    ]
    draw_text_lines(frame, right_lines, w - 345, 35, dy=30, font_scale=0.58)

    draw_zoom_bar(frame, zoom_factor, ZOOM_MIN, ZOOM_MAX)

# ==========================================
# MAIN
# ==========================================
def main():
    picam2 = Picamera2()

    config = picam2.create_preview_configuration(
        main={"size": (CAPTURE_WIDTH, CAPTURE_HEIGHT), "format": "RGB888"},
        buffer_count=4
    )
    picam2.configure(config)
    picam2.start()

    time.sleep(2.0)

    metadata = picam2.capture_metadata()
    base_crop = tuple(int(v) for v in metadata["ScalerCrop"])

    zoom_factor = clamp(START_ZOOM, ZOOM_MIN, ZOOM_MAX)
    apply_zoom(picam2, base_crop, zoom_factor)

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)

    capture_pending = False
    capture_time = 0.0
    last_saved_text = ""
    last_saved_until = 0.0

    try:
        while True:
            frame_rgb = picam2.capture_array("main")
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            preview = frame_bgr.copy()
            now = time.monotonic()

            remaining_time = max(0.0, capture_time - now) if capture_pending else 0.0

            if capture_pending and now >= capture_time:
                out_path = make_output_path(SAVE_DIR)
                cv2.imwrite(out_path, frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                last_saved_text = f"Saved: {out_path}"
                last_saved_until = now + 3.0
                capture_pending = False

            if now > last_saved_until:
                last_saved_text = ""

            draw_ui(preview, zoom_factor, capture_pending, remaining_time, last_saved_text)
            cv2.imshow(WINDOW_NAME, preview)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("k") and not capture_pending:
                capture_pending = True
                capture_time = time.monotonic() + DELAY_SECONDS

            elif key == ord("z"):
                zoom_factor = clamp(round(zoom_factor - FINE_ZOOM_STEP, 2), ZOOM_MIN, ZOOM_MAX)
                apply_zoom(picam2, base_crop, zoom_factor)

            elif key == ord("x"):
                zoom_factor = clamp(round(zoom_factor + FINE_ZOOM_STEP, 2), ZOOM_MIN, ZOOM_MAX)
                apply_zoom(picam2, base_crop, zoom_factor)

            elif key == ord("a"):
                zoom_factor = clamp(round(zoom_factor - COARSE_ZOOM_STEP, 2), ZOOM_MIN, ZOOM_MAX)
                apply_zoom(picam2, base_crop, zoom_factor)

            elif key == ord("d"):
                zoom_factor = clamp(round(zoom_factor + COARSE_ZOOM_STEP, 2), ZOOM_MIN, ZOOM_MAX)
                apply_zoom(picam2, base_crop, zoom_factor)

            elif key == ord("0"):
                zoom_factor = 1.00
                apply_zoom(picam2, base_crop, zoom_factor)

            elif key == ord("q"):
                break

    finally:
        cv2.destroyAllWindows()
        picam2.stop()
        picam2.close()

if __name__ == "__main__":
    main()