import os
import time
from datetime import datetime

import cv2
from picamera2 import Picamera2

# ==========================================
# USER SETTINGS
# ==========================================
SAVE_DIR = "/home/jekaca/camera/manual"   # Editable save path
CAPTURE_WIDTH = 720                               # Editable capture width
CAPTURE_HEIGHT = 720                              # Editable capture height
DELAY_SECONDS = 3.0                               # Delay after pressing 'k'
JPEG_QUALITY = 95                                 # 0 to 100

ZOOM_MIN = 1.00                                   # Default/full view
ZOOM_MAX = 4.00                                   # Max digital zoom
FINE_ZOOM_STEP = 0.02                             # Small step
COARSE_ZOOM_STEP = 0.10                           # Bigger step
START_ZOOM = 1.00

WINDOW_NAME = "Camera_Ver_1_Zoom"

# ==========================================
# HELPERS
# ==========================================
def clamp(value, low, high):
    return max(low, min(high, value))

def make_even(n):
    return int(n) if int(n) % 2 == 0 else int(n) - 1

def make_output_path(folder: str) -> str:
    os.makedirs(folder, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(folder, f"img_{ts}.jpg")

def apply_zoom(picam2, base_crop, zoom_factor):
    """
    base_crop = (x, y, w, h) representing the default full crop
    for the current camera mode.
    """
    x0, y0, w0, h0 = base_crop

    new_w = max(64, make_even(w0 / zoom_factor))
    new_h = max(64, make_even(h0 / zoom_factor))

    # Center crop
    new_x = make_even(x0 + (w0 - new_w) / 2)
    new_y = make_even(y0 + (h0 - new_h) / 2)

    picam2.set_controls({"ScalerCrop": [new_x, new_y, new_w, new_h]})

def draw_lines(frame, lines, x=10, y=28, dy=28):
    for line in lines:
        cv2.putText(
            frame,
            line,
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (0, 255, 0),
            2,
            cv2.LINE_AA
        )
        y += dy

def draw_zoom_bar(frame, zoom_value, zoom_min, zoom_max):
    h, w = frame.shape[:2]
    bar_x = 10
    bar_y = h - 28
    bar_w = 260
    bar_h = 14

    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (255, 255, 255), 1)

    ratio = 0.0
    if zoom_max > zoom_min:
        ratio = (zoom_value - zoom_min) / (zoom_max - zoom_min)
    ratio = max(0.0, min(1.0, ratio))

    fill_w = int(bar_w * ratio)
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), (0, 255, 0), -1)

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

    # Default crop for current mode
    metadata = picam2.capture_metadata()
    base_crop = tuple(int(v) for v in metadata["ScalerCrop"])

    zoom_factor = clamp(START_ZOOM, ZOOM_MIN, ZOOM_MAX)
    apply_zoom(picam2, base_crop, zoom_factor)

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)

    capture_pending = False
    capture_time = 0.0
    last_saved_text = ""
    last_saved_until = 0.0

    print("Controls:")
    print("  k = start delayed capture")
    print("  z = zoom out fine")
    print("  x = zoom in fine")
    print("  a = zoom out coarse")
    print("  d = zoom in coarse")
    print("  0 = reset zoom")
    print("  q = quit")

    try:
        while True:
            frame_rgb = picam2.capture_array("main")
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            preview = frame_bgr.copy()
            now = time.monotonic()

            lines = [
                f"Resolution: {CAPTURE_WIDTH} x {CAPTURE_HEIGHT}",
                f"Delay: {DELAY_SECONDS:.1f} sec",
                f"Zoom: {zoom_factor:.2f}x",
                "k=capture  z/x=fine zoom  a/d=coarse zoom  0=reset  q=quit"
            ]

            if capture_pending:
                remaining = max(0.0, capture_time - now)
                lines.append(f"Capturing in: {remaining:.1f} sec")
                if now >= capture_time:
                    out_path = make_output_path(SAVE_DIR)
                    cv2.imwrite(out_path, frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                    last_saved_text = f"Saved: {out_path}"
                    last_saved_until = now + 2.5
                    capture_pending = False

            if now < last_saved_until:
                lines.append(last_saved_text)

            draw_lines(preview, lines)
            draw_zoom_bar(preview, zoom_factor, ZOOM_MIN, ZOOM_MAX)
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