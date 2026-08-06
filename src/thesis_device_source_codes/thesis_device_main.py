#!/usr/bin/env python3
"""
Integrated Raspberry Pi 4 thesis device
---------------------------------------
Features:
- Edge Impulse image classification / FOMO object detection (.eim)
- Picamera2 live preview
- HX711 live weight reading with rolling trimmed-average stable display filter
- Tare button on BCM GPIO27 / physical pin 13
- Soft tare by short press, hard zero/reset by long press
- 8 kg load-cell warning/overload protection
- I2C 16x2 LCD display
- Active-HIGH confirmation button on GPIO17
- BTS7960-driven linear actuator sealing cycle
- Adjustable actuator default position before button press
- USB thermal printer receipt + EAN13 barcode
- SQLite offline storage:
    1) vegetable_price.db
    2) customer_transactions.db

Confirmed hardware mapping:
- Button: GPIO17, active-HIGH
- BTS7960 RPWM: GPIO23
- BTS7960 LPWM: GPIO24
- HX711 DT: GPIO6
- HX711 SCK: GPIO5
- LCD I2C: SDA GPIO2, SCL GPIO3, address 0x27
- Printer: /dev/usb/lp0
- Tare button: GPIO27 / physical pin 13, active-HIGH
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Optional

import cv2
import numpy as np
from escpos.printer import File
from gpiozero import Button, DigitalOutputDevice
from picamera2 import Picamera2
from edge_impulse_linux.image import ImageImpulseRunner
from HX711 import SimpleHX711, Mass, Options, ReadType, Value
from RPLCD.i2c import CharLCD


# =========================================================
# FILE PATHS
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = "/home/jekaca/Thesis/super_duper_final_fomo-linux-aarch64-v4-impulse-#2.eim"
# Primary calibration file from your latest L6N 8kg moving-average scale code.
# If this file is not found, the program automatically falls back to the old
# hx711_calibration.json beside this script.
CAL_FILE = Path("/home/jekaca/virtual_environment/recreate/loadSensor_and_lcd_venv_rpi4/hx711_l6n_average_filter_calibration.json")
LEGACY_CAL_FILE = BASE_DIR / "hx711_calibration.json"

TXN_DB_PATH = "/home/jekaca/Thesis/final_device_3.1/customer_transactions.db"
VEG_DB_PATH = "/home/jekaca/Thesis/final_device_3.1/vegetable_price.db"
#VEG_DB_PATH = BASE_DIR / "vegetable_price.db"
# TXN_DB_PATH = BASE_DIR / "customer_transactions.db"

# =========================================================
# CAMERA / MODEL
# =========================================================
MODEL_WIDTH = 96
MODEL_HEIGHT = 96

# IMPORTANT:
# Your latest instruction says detections below 60% should be ignored.
# This value is used for both FOMO object boxes and classification confidence.
MIN_PRODUCT_CONFIDENCE = 0.60

SMOOTHING_FRAMES = 5
INFER_INTERVAL = 0.25
CAMERA_WARMUP_SEC = 1.0

CAPTURE_WIDTH = 960
CAPTURE_HEIGHT = 960

WINDOW_NAME = "Vegetable Detection + Weigh + Seal + Print"
PREVIEW_WIDTH = 900
PREVIEW_HEIGHT = 900

# =========================================================
# SENSOR-LEVEL DIGITAL ZOOM
# =========================================================
# This uses the same square sensor-crop zoom idea as your separate IMX219
# zoom test code. At 1.00x, the camera uses a CENTERED SQUARE crop from
# the full IMX219 sensor, then scales it to 960 x 960.
#
# This is the important part for your dataset problem:
# - Preview and inference use the SAME square camera view.
# - 1.00x is loaded automatically at startup.
# - 1.00x here means the full centered square sensor crop, similar to your
#   uploaded marble potato sample image.
# - Higher values crop tighter from the center for sensor-level digital zoom.
CAMERA_ZOOM_DEFAULT = 1.00
CAMERA_ZOOM_MIN = 1.00
CAMERA_ZOOM_MAX = 4.00
CAMERA_ZOOM_STEP_FINE = 0.02
CAMERA_ZOOM_STEP_COARSE = 0.10
MIN_SCALER_CROP_SIZE = 64

EMPTY_LIKE_LABELS = {"empty", "background", "none", "no object"}

# =========================================================
# HX711 / GPIO
# =========================================================
DT_PIN = 6
SCK_PIN = 5

# Weight reading is now based on lcdAndWeight_3_l6n_6_ref_code0_moving_average.py.
# Concept used:
# 1) median raw read
# 2) raw-to-grams conversion from calibration
# 3) rolling trimmed average
# 4) stability window
# 5) display hold while moving
# 6) 1-decimal output with 0.1 g step
RAW_READS_PER_SAMPLE = 3
WEIGHT_READ_INTERVAL = 0.05

AVERAGE_WINDOW = 10
AVERAGE_TRIM_RATIO = 0.15

STABILITY_WINDOW = 8
STABLE_RANGE_G = 0.4
VERY_STABLE_RANGE_G = 0.2
STABLE_REQUIRED_COUNT = 4

DISPLAY_STEP_G = 0.1
DISPLAY_DECIMALS = 1

ZERO_DEADBAND_G = 0.3
NEGATIVE_CLAMP = False  # False is required so soft tare can show negative weight when the tared load is removed.

DISPLAY_HOLD_WHEN_MOVING = True
BIG_CHANGE_UPDATE_G = 3.0

AUTOZERO_ENABLE = True
AUTOZERO_BAND_G = 0.8
AUTOZERO_STABLE_RANGE_G = 0.25
AUTOZERO_CONSECUTIVE = 15
AUTOZERO_CORRECTION_G = 0.01

WARMUP_READS = 5
WEIGHT_CONSOLE_UPDATE_INTERVAL = 0.25

# ZEMIC L6N load-cell safety. Tare does not remove actual physical load,
# so overload checks use gross load against the hard-zero baseline.
LOAD_CELL_MAX_CAPACITY_G = 8000.0
LOAD_CELL_WARNING_G = 7500.0
LOAD_CELL_OVERLOAD_G = 8000.0
BLOCK_PRINT_WHEN_OVERLOAD = True

# =========================================================
# LCD
# =========================================================
LCD_I2C_ADDRESS = 0x27
LCD_I2C_PORT = 1
LCD_COLS = 16
LCD_ROWS = 2
LCD_REFRESH_INTERVAL = 0.20

# =========================================================
# BUTTON / ACTUATOR / BTS7960
# =========================================================
BTN_PIN = 17
TARE_BTN_PIN = 27  # physical pin 13, active-HIGH
RPWM_PIN = 23
LPWM_PIN = 24
BUTTON_BOUNCE_S = 0.04
TARE_BUTTON_BOUNCE_S = 0.04
TARE_LONG_PRESS_S = 1.50

# =========================================================
# ADJUSTABLE ACTUATOR POSITION SETTINGS
# =========================================================
# Because the linear actuator has NO position feedback sensor, all positions
# are controlled by time. You must calibrate these seconds on the real sealer.

# Desired default position when the OK/confirmation button is NOT pressed.
# User request: default should be maximum length / extend position.
# Allowed values: "extended" or "retracted"
DEFAULT_POSITION_BEFORE_PRESS = "extended"

# Position to move toward after the OK/confirmation button is pressed.
# If DEFAULT_POSITION_BEFORE_PRESS = "extended", this is normally "retracted".
# Allowed values: "extended" or "retracted"
POSITION_AFTER_PRESS = "retracted"

# Move time to force actuator toward default position.
# Increase until it reaches your desired default/max extend position.
DEFAULT_POSITION_MOVE_TIME_S = 12.5

# Move time from default position toward position_after_press.
# This controls how far the actuator retracts/presses after button press.
POSITION_AFTER_PRESS_MOVE_TIME_S = 12.5

# Keep actuator stopped while sealer is pressed / in final pressed position.
PRESS_HOLD_TIME_S = 4

# Extra waiting time before returning to the default position.
RETURN_TO_DEFAULT_DELAY_S = 0.00

# Pause between changing motor directions to protect the driver/actuator.
DIR_CHANGE_PAUSE_S = 0.20

# If True, the program moves actuator to DEFAULT_POSITION_BEFORE_PRESS at startup.
# Keep True if you want the actuator to automatically prepare itself before use.
MOVE_TO_DEFAULT_ON_STARTUP = True

# If True, it also moves toward the default position before every sealing cycle.
# Usually False is better after startup, because the actuator is already returned
# to default after each completed button cycle.
ENSURE_DEFAULT_BEFORE_EACH_CYCLE = False

# Safety
ALLOW_TRIGGER_WITHOUT_VALID_PRODUCT = False
MIN_WEIGHT_TO_ALLOW_PRINT_G = 1.0

# =========================================================
# THERMAL PRINTER
# =========================================================
PRINTER_ENABLED = True
PRINTER_DEVICE = "/dev/usb/lp0"
PRINT_FEED_LINES = 3
BARCODE_HEIGHT = 80
BARCODE_WIDTH = 3

# =========================================================
# DATABASE SETTINGS
# =========================================================
DEFAULT_VEGETABLES = [
    ("onion", "ONION", 100.0, 1),
    ("garlic", "GARLIC", 180.0, 1),
    ("marble_potato", "MARBLE POTATO", 120.0, 1),
]

# =========================================================
# GLOBAL LOCKS / STATE
# =========================================================
state_lock = Lock()
printer_lock = Lock()
action_lock = Lock()
actuator_lock = Lock()


@dataclass
class SystemState:
    detected_label: str = "none"
    display_name: str = "NO PRODUCT"
    confidence: float = 0.0
    camera_zoom: float = CAMERA_ZOOM_DEFAULT
    weight_g: float = 0.0
    weight_status: str = "MOVING"
    weight_span_g: float = 0.0
    gross_weight_g: float = 0.0
    tare_mode: str = "NONE"
    load_warning: bool = False
    overloaded: bool = False
    price_per_kg: float = 0.0
    total_price: float = 0.0
    valid_product: bool = False
    multiple_detected: bool = False
    detected_types: list[str] = field(default_factory=list)
    status_message: str = "READY"
    busy: bool = False
    last_barcode: str = ""
    last_transaction_id: Optional[int] = None


@dataclass
class WeightFilterState:
    dynamic_offset_raw: float
    hard_zero_offset_raw: float = 0.0
    tare_mode: str = "NONE"
    last_raw: Optional[float] = None
    last_instant_grams: float = 0.0
    last_averaged_grams: float = 0.0
    average_window: deque = field(default_factory=lambda: deque(maxlen=AVERAGE_WINDOW))
    stability_window: deque = field(default_factory=lambda: deque(maxlen=STABILITY_WINDOW))
    display_grams: Optional[float] = None
    stable_counter: int = 0
    near_zero_counter: int = 0


system_state = SystemState()

# GPIO devices
rpwm = DigitalOutputDevice(RPWM_PIN, active_high=True, initial_value=False)
lpwm = DigitalOutputDevice(LPWM_PIN, active_high=True, initial_value=False)
button = Button(BTN_PIN, pull_up=False, bounce_time=BUTTON_BOUNCE_S)
tare_button = Button(TARE_BTN_PIN, pull_up=False, bounce_time=TARE_BUTTON_BOUNCE_S)


# =========================================================
# DATABASE FUNCTIONS
# =========================================================
def get_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_databases() -> None:
    """Create both databases and seed default vegetables if missing."""
    with get_conn(VEG_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vegetables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                price_per_kg REAL NOT NULL CHECK(price_per_kg >= 0),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        for name, display_name, price_per_kg, is_active in DEFAULT_VEGETABLES:
            conn.execute(
                """
                INSERT INTO vegetables (name, display_name, price_per_kg, is_active)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO NOTHING
                """,
                (name, display_name, price_per_kg, is_active),
            )

        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_vegetables_updated_at
            AFTER UPDATE ON vegetables
            FOR EACH ROW
            BEGIN
                UPDATE vegetables
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = NEW.id;
            END;
            """
        )
        conn.commit()

    with get_conn(TXN_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barcode_ean13 TEXT NOT NULL UNIQUE,
                vegetable_name TEXT NOT NULL,
                vegetable_display_name TEXT NOT NULL,
                raw_detected_label TEXT NOT NULL,
                confidence REAL NOT NULL,
                weight_g REAL NOT NULL CHECK(weight_g >= 0),
                price_per_kg REAL NOT NULL CHECK(price_per_kg >= 0),
                total_price REAL NOT NULL CHECK(total_price >= 0),
                transaction_time TEXT NOT NULL,
                source_device TEXT NOT NULL DEFAULT 'raspberry_pi_4_offline'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_transactions_barcode ON customer_transactions(barcode_ean13)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_transactions_time ON customer_transactions(transaction_time)"
        )
        conn.commit()


def fetch_active_vegetables() -> dict[str, dict]:
    """Return active vegetables keyed by normalized name."""
    products: dict[str, dict] = {}
    with get_conn(VEG_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT name, display_name, price_per_kg
            FROM vegetables
            WHERE is_active = 1
            ORDER BY name
            """
        ).fetchall()

    for row in rows:
        products[row["name"].strip().lower()] = {
            "display_name": row["display_name"],
            "price_per_kg": float(row["price_per_kg"]),
        }
    return products


def create_ean13_from_id(txn_id: int) -> str:
    """
    Build a numeric-only EAN13 barcode from the transaction id.
    Base 12 digits = transaction id zero-padded to 12 digits.
    Digit 13 = EAN13 check digit.
    """
    base12 = f"{txn_id:012d}"
    return base12 + ean13_check_digit(base12)


def insert_transaction(snapshot: SystemState) -> tuple[int, str]:
    """Insert a transaction and generate a unique EAN13 barcode from the DB id."""
    transaction_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_conn(TXN_DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO customer_transactions (
                barcode_ean13,
                vegetable_name,
                vegetable_display_name,
                raw_detected_label,
                confidence,
                weight_g,
                price_per_kg,
                total_price,
                transaction_time
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "PENDING",
                normalize_label(snapshot.detected_label),
                snapshot.display_name,
                snapshot.detected_label,
                snapshot.confidence,
                round(snapshot.weight_g, 2),
                round(snapshot.price_per_kg, 2),
                round(snapshot.total_price, 2),
                transaction_time,
            ),
        )
        txn_id = int(cursor.lastrowid)
        barcode = create_ean13_from_id(txn_id)

        cursor.execute(
            """
            UPDATE customer_transactions
            SET barcode_ean13 = ?
            WHERE id = ?
            """,
            (barcode, txn_id),
        )
        conn.commit()

    return txn_id, barcode


# =========================================================
# HELPER FUNCTIONS
# =========================================================
def load_weight_calibration() -> tuple[float, float, dict, Path]:
    """
    Load calibration from the latest L6N moving-average calibration format.

    Supported formats:
    1) New stable scale file:
       {"offset_raw": ..., "scale_raw_per_gram": ...}
    2) Old thesis file:
       {"offset": ..., "ref_unit_int": ...}
    """
    candidates = [CAL_FILE, LEGACY_CAL_FILE]

    for path in candidates:
        path = Path(path)
        if not path.exists():
            continue

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if "offset_raw" in data and "scale_raw_per_gram" in data:
            return float(data["offset_raw"]), float(data["scale_raw_per_gram"]), data, path

        if "offset" in data and "ref_unit_int" in data:
            return float(data["offset"]), float(data["ref_unit_int"]), data, path

        raise RuntimeError(f"Invalid calibration file format: {path}")

    raise FileNotFoundError(
        "No HX711 calibration file found. Checked: "
        + ", ".join(str(Path(x)) for x in candidates)
    )


def init_lcd() -> CharLCD:
    lcd = CharLCD(
        i2c_expander="PCF8574",
        address=LCD_I2C_ADDRESS,
        port=LCD_I2C_PORT,
        cols=LCD_COLS,
        rows=LCD_ROWS,
        dotsize=8,
    )
    lcd.clear()
    return lcd


def lcd_show(lcd: CharLCD, line1: str = "", line2: str = "") -> None:
    lcd.home()
    lcd.write_string(f"{line1[:LCD_COLS]:<{LCD_COLS}}")
    lcd.crlf()
    lcd.write_string(f"{line2[:LCD_COLS]:<{LCD_COLS}}")


def read_raw_median(hx: SimpleHX711) -> int:
    return int(hx.read(Options(RAW_READS_PER_SAMPLE, ReadType.Median)))


def warmup_hx711(hx: SimpleHX711) -> None:
    for _ in range(WARMUP_READS):
        try:
            read_raw_median(hx)
        except Exception:
            pass
        time.sleep(0.05)


def round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(value / step) * step


def format_grams_1_decimal(grams: float) -> str:
    return f"{grams:.1f}"


def raw_to_grams(raw: float, offset_raw: float, scale_raw_per_gram: float) -> float:
    if scale_raw_per_gram == 0:
        raise RuntimeError("scale_raw_per_gram is zero. Recalibrate the scale.")
    return (raw - offset_raw) / scale_raw_per_gram


def reset_filter_windows(weight_filter: WeightFilterState, display_value: float = 0.0) -> None:
    weight_filter.average_window.clear()
    weight_filter.stability_window.clear()
    weight_filter.display_grams = round(display_value, DISPLAY_DECIMALS)
    weight_filter.stable_counter = STABLE_REQUIRED_COUNT
    weight_filter.near_zero_counter = 0


def offset_from_current_average(weight_filter: WeightFilterState, scale_raw_per_gram: float) -> float:
    """Return a smooth raw offset that makes the current displayed/net load become 0 g."""
    if weight_filter.last_raw is None:
        return float(weight_filter.dynamic_offset_raw)
    return float(weight_filter.dynamic_offset_raw + (weight_filter.last_averaged_grams * scale_raw_per_gram))


def apply_soft_tare(weight_filter: WeightFilterState, scale_raw_per_gram: float) -> None:
    """Short press: set current load as temporary net zero. Removing it can show negative weight."""
    new_offset = offset_from_current_average(weight_filter, scale_raw_per_gram)
    weight_filter.dynamic_offset_raw = new_offset
    weight_filter.tare_mode = "NET TARE"
    reset_filter_windows(weight_filter, 0.0)
    print(f"[TARE] Soft tare applied. New dynamic_offset_raw={new_offset:.2f}")


def apply_hard_zero(weight_filter: WeightFilterState, scale_raw_per_gram: float) -> None:
    """Long press: hard-reset the scale baseline to the current load condition."""
    new_offset = offset_from_current_average(weight_filter, scale_raw_per_gram)
    weight_filter.dynamic_offset_raw = new_offset
    weight_filter.hard_zero_offset_raw = new_offset
    weight_filter.tare_mode = "HARD ZERO"
    reset_filter_windows(weight_filter, 0.0)
    print(f"[TARE] Hard zero/reset applied. New hard_zero_offset_raw={new_offset:.2f}")


def get_gross_weight_g(raw: float, hard_zero_offset_raw: float, scale_raw_per_gram: float) -> float:
    try:
        return abs(raw_to_grams(raw, hard_zero_offset_raw, scale_raw_per_gram))
    except Exception:
        return 0.0


def load_safety_status(gross_weight_g: float) -> tuple[bool, bool, str]:
    overloaded = gross_weight_g >= LOAD_CELL_OVERLOAD_G
    warning = gross_weight_g >= LOAD_CELL_WARNING_G
    if overloaded:
        return warning, overloaded, "OVERLOAD"
    if warning:
        return warning, overloaded, "NEAR LIMIT"
    return warning, overloaded, "OK"


def clean_weight_for_display(grams: float) -> float:
    if abs(grams) <= ZERO_DEADBAND_G:
        grams = 0.0
    if NEGATIVE_CLAMP and grams < 0:
        grams = 0.0
    grams = round_to_step(grams, DISPLAY_STEP_G)
    return round(grams, DISPLAY_DECIMALS)


def rolling_trimmed_average(values, trim_ratio: float = 0.15) -> float:
    values = list(values)
    if len(values) == 0:
        return 0.0
    if len(values) < 5:
        return statistics.mean(values)

    values = sorted(values)
    trim = int(len(values) * trim_ratio)
    if trim > 0 and len(values) > trim * 2:
        values = values[trim:-trim]
    return statistics.mean(values)


def update_weight_filter(
    hx: SimpleHX711,
    weight_filter: WeightFilterState,
    scale_raw_per_gram: float,
) -> tuple[float, str, float, float, float, int, float, bool, bool, str]:
    """
    One non-blocking live-scale update based on your stable L6N average filter.

    Returns:
        display_grams, status, span, instant_grams, averaged_grams, raw,
        gross_weight_g, load_warning, overloaded, load_status
    """
    raw = read_raw_median(hx)
    weight_filter.last_raw = float(raw)

    instant_grams = raw_to_grams(
        raw,
        weight_filter.dynamic_offset_raw,
        scale_raw_per_gram,
    )

    weight_filter.average_window.append(instant_grams)

    averaged_grams = rolling_trimmed_average(
        weight_filter.average_window,
        trim_ratio=AVERAGE_TRIM_RATIO,
    )
    weight_filter.last_instant_grams = float(instant_grams)
    weight_filter.last_averaged_grams = float(averaged_grams)

    weight_filter.stability_window.append(averaged_grams)

    span = 0.0
    stable = False

    if len(weight_filter.stability_window) == STABILITY_WINDOW:
        span = max(weight_filter.stability_window) - min(weight_filter.stability_window)
        stable = span <= STABLE_RANGE_G

    if stable:
        weight_filter.stable_counter += 1
    else:
        weight_filter.stable_counter = 0

    if AUTOZERO_ENABLE and len(weight_filter.stability_window) == STABILITY_WINDOW:
        near_zero = abs(averaged_grams) <= AUTOZERO_BAND_G
        very_stable_zero = span <= AUTOZERO_STABLE_RANGE_G

        if near_zero and very_stable_zero:
            weight_filter.near_zero_counter += 1
        else:
            weight_filter.near_zero_counter = 0

        if weight_filter.near_zero_counter >= AUTOZERO_CONSECUTIVE:
            correction_raw = abs(scale_raw_per_gram * AUTOZERO_CORRECTION_G)
            raw_error = raw - weight_filter.dynamic_offset_raw

            if abs(raw_error) > correction_raw:
                if raw_error > 0:
                    weight_filter.dynamic_offset_raw += correction_raw
                else:
                    weight_filter.dynamic_offset_raw -= correction_raw

    target_display = clean_weight_for_display(averaged_grams)
    target_display = round(target_display, DISPLAY_DECIMALS)

    if weight_filter.display_grams is None:
        weight_filter.display_grams = target_display
    else:
        difference_from_display = abs(target_display - weight_filter.display_grams)

        if weight_filter.stable_counter >= STABLE_REQUIRED_COUNT:
            weight_filter.display_grams = target_display
        else:
            if DISPLAY_HOLD_WHEN_MOVING:
                if difference_from_display >= BIG_CHANGE_UPDATE_G:
                    weight_filter.display_grams = target_display
            else:
                weight_filter.display_grams = target_display

    weight_filter.display_grams = round(weight_filter.display_grams, DISPLAY_DECIMALS)
    status = "STABLE" if weight_filter.stable_counter >= STABLE_REQUIRED_COUNT else "MOVING"

    gross_weight_g = get_gross_weight_g(
        raw,
        weight_filter.hard_zero_offset_raw,
        scale_raw_per_gram,
    )
    load_warning, overloaded, load_status = load_safety_status(gross_weight_g)

    return (
        weight_filter.display_grams,
        status,
        span,
        instant_grams,
        averaged_grams,
        raw,
        gross_weight_g,
        load_warning,
        overloaded,
        load_status,
    )


def center_crop_to_square(img_bgr: np.ndarray) -> np.ndarray:
    h, w = img_bgr.shape[:2]
    side = min(h, w)
    y0 = (h - side) // 2
    x0 = (w - side) // 2
    return img_bgr[y0:y0 + side, x0:x0 + side]


def model_view_from_frame(frame_bgr: np.ndarray) -> np.ndarray:
    sq = center_crop_to_square(frame_bgr)
    return cv2.resize(sq, (MODEL_WIDTH, MODEL_HEIGHT), interpolation=cv2.INTER_AREA)


def clamp_zoom(zoom: float) -> float:
    try:
        value = float(zoom)
    except (TypeError, ValueError):
        value = CAMERA_ZOOM_DEFAULT
    return max(CAMERA_ZOOM_MIN, min(CAMERA_ZOOM_MAX, value))


def get_sensor_square_crop(picam2: Picamera2) -> tuple[int, int, int, int]:
    """
    Build the centered square crop from the real IMX219 sensor area.

    For Raspberry Pi Camera Module V2 / IMX219, the full sensor is normally
    3280 x 2464. A square crop uses the full 2464-pixel height and removes
    equal left/right sides. That gives the same kind of square field-of-view
    as your separate default zoom = 1.00 test code.
    """
    pixel_array = picam2.camera_properties.get("PixelArraySize", None)

    if pixel_array is None:
        # Safe fallback. This still keeps the program running if the camera
        # does not expose PixelArraySize for some reason.
        sensor_w = CAPTURE_WIDTH
        sensor_h = CAPTURE_HEIGHT
    else:
        sensor_w, sensor_h = pixel_array

    side = min(int(sensor_w), int(sensor_h))
    x = (int(sensor_w) - side) // 2
    y = (int(sensor_h) - side) // 2

    # Even values are safer for the camera scaler.
    x -= x % 2
    y -= y % 2
    side -= side % 2

    return int(x), int(y), int(side), int(side)


def zoom_crop_from_base(
    base_crop: tuple[int, int, int, int],
    zoom_factor: float,
) -> tuple[int, int, int, int]:
    """
    Create a smaller centered square crop inside the base square sensor crop.

    zoom_factor = 1.00 means use the full base square crop.
    zoom_factor = 2.00 means crop width/height are half of the base crop.
    """
    bx, by, bw, bh = base_crop
    zoom_factor = clamp_zoom(zoom_factor)

    side = min(int(bw), int(bh))
    crop_side = int(side / zoom_factor)
    crop_side = max(MIN_SCALER_CROP_SIZE, min(crop_side, side))

    # Even dimensions are safer for the camera scaler.
    crop_side -= crop_side % 2

    x = int(bx + (bw - crop_side) // 2)
    y = int(by + (bh - crop_side) // 2)

    x -= x % 2
    y -= y % 2

    return int(x), int(y), int(crop_side), int(crop_side)


def apply_camera_sensor_zoom(
    picam2: Picamera2,
    zoom: float,
    base_sensor_crop: tuple[int, int, int, int],
) -> tuple[float, tuple[int, int, int, int]]:
    """
    Apply square sensor-crop zoom using Picamera2 ScalerCrop.

    This changes the actual camera/ISP crop used by both the OpenCV preview
    and the Edge Impulse inference frame. It is not just OpenCV resize zoom.
    """
    zoom = clamp_zoom(round(float(zoom), 2))
    crop = zoom_crop_from_base(base_sensor_crop, zoom)

    try:
        picam2.set_controls({"ScalerCrop": crop})
    except Exception as e:
        print(f"[WARN] Failed to apply ScalerCrop: {e}")

    return zoom, crop


def short_price(price: float) -> str:
    return f"P{price:.2f}"


def normalize_label(label: str) -> str:
    return str(label).strip().lower().replace(" ", "_")


def ean13_check_digit(first12: str) -> str:
    if len(first12) != 12 or not first12.isdigit():
        raise ValueError("EAN-13 base must be exactly 12 digits.")
    total = 0
    for i, ch in enumerate(first12):
        digit = int(ch)
        total += digit if i % 2 == 0 else digit * 3
    return str((10 - (total % 10)) % 10)


def clamp_time(seconds: float) -> float:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, value)


def draw_text(img: np.ndarray, text: str, org: tuple[int, int], scale: float = 0.65, thickness: int = 2) -> None:
    x, y = org
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness + 3, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thickness, cv2.LINE_AA)


def build_ui_frame(frame_bgr: np.ndarray, s: SystemState) -> np.ndarray:
    display = cv2.resize(frame_bgr, (PREVIEW_WIDTH, PREVIEW_HEIGHT), interpolation=cv2.INTER_LINEAR)
    cv2.rectangle(display, (10, 10), (590, 300), (40, 40, 40), -1)

    busy_text = "BUSY" if s.busy else s.status_message
    draw_text(display, f"Status: {busy_text}", (25, 40), 0.75)
    draw_text(display, f"Detected: {s.display_name}", (25, 75), 0.72)
    draw_text(display, f"Confidence: {s.confidence * 100:.1f}%", (25, 110), 0.66)
    draw_text(display, f"Types: {', '.join(s.detected_types) if s.detected_types else '-'}", (25, 145), 0.58)
    draw_text(display, f"Weight: {s.weight_g:.1f} g ({s.weight_status})", (25, 180), 0.62)
    draw_text(display, f"Gross Load: {s.gross_weight_g:.1f} g", (25, 215), 0.58)
    draw_text(display, f"Tare: {s.tare_mode}", (25, 245), 0.58)
    draw_text(display, f"Price/KG: PHP {s.price_per_kg:.2f}", (25, 275), 0.62)
    draw_text(display, f"Total: PHP {s.total_price:.2f}", (25, 305), 0.62)
    draw_text(display, f"Last Code: {s.last_barcode or '-'}", (25, 335), 0.52)

    draw_text(display, f"Square Sensor Zoom: {s.camera_zoom:.2f}x", (610, 35), 0.60)
    draw_text(display, "D / +  Fine Zoom In", (610, 65), 0.56)
    draw_text(display, "A / -  Fine Zoom Out", (610, 95), 0.56)
    draw_text(display, "C / Z  Coarse In/Out", (610, 125), 0.56)
    draw_text(display, "0 / R  Reset 1.00x", (610, 155), 0.56)
    draw_text(display, "GPIO17 = Confirm / Print / Seal", (610, 195), 0.56)
    draw_text(display, "GPIO27 = Tare | hold = Hard Zero", (610, 225), 0.52)
    if s.overloaded:
        draw_text(display, "LOAD CELL OVERLOAD - REMOVE WEIGHT", (610, 265), 0.52)
    elif s.load_warning:
        draw_text(display, "WARNING: LOAD CELL NEAR 8KG", (610, 265), 0.52)
    draw_text(display, "Q = Quit", (610, 305), 0.56)
    return display


def capture_snapshot() -> SystemState:
    with state_lock:
        return SystemState(
            detected_label=system_state.detected_label,
            display_name=system_state.display_name,
            confidence=system_state.confidence,
            camera_zoom=system_state.camera_zoom,
            weight_g=system_state.weight_g,
            weight_status=system_state.weight_status,
            weight_span_g=system_state.weight_span_g,
            gross_weight_g=system_state.gross_weight_g,
            tare_mode=system_state.tare_mode,
            load_warning=system_state.load_warning,
            overloaded=system_state.overloaded,
            price_per_kg=system_state.price_per_kg,
            total_price=system_state.total_price,
            valid_product=system_state.valid_product,
            multiple_detected=system_state.multiple_detected,
            detected_types=list(system_state.detected_types),
            status_message=system_state.status_message,
            busy=system_state.busy,
            last_barcode=system_state.last_barcode,
            last_transaction_id=system_state.last_transaction_id,
        )


# =========================================================
# EDGE IMPULSE RESULT PARSING
# =========================================================
def extract_confidence(item: dict) -> float:
    """Read confidence from common Edge Impulse object-detection keys."""
    for key in ("value", "confidence", "score", "probability"):
        if key in item:
            try:
                return float(item[key])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def analyze_inference_result(result: dict, products: dict[str, dict]) -> tuple[list[str], dict[str, float]]:
    """
    Returns:
        detected_types: vegetable labels above MIN_PRODUCT_CONFIDENCE
        best_conf_by_label: best confidence per detected label

    Supports both:
    - FOMO/object detection result: result["result"]["bounding_boxes"]
    - Classification result: result["result"Latest Instruction (The very important or the most priority instruction to be executed for now):]["classification"]
    """
    result_block = result.get("result", {}) if isinstance(result, dict) else {}
    best_conf_by_label: dict[str, float] = {}

    bounding_boxes = (
        result_block.get("bounding_boxes")
        or result_block.get("boundingBoxes")
        or result_block.get("objects")
        or []
    )

    if isinstance(bounding_boxes, list) and bounding_boxes:
        for box in bounding_boxes:
            if not isinstance(box, dict):
                continue
            label = normalize_label(box.get("label", ""))
            conf = extract_confidence(box)
            if conf < MIN_PRODUCT_CONFIDENCE:
                continue
            if label in EMPTY_LIKE_LABELS:
                continue
            if label not in products:
                continue
            best_conf_by_label[label] = max(best_conf_by_label.get(label, 0.0), conf)
    else:
        classification = result_block.get("classification", {})
        if isinstance(classification, dict):
            for label_raw, conf_raw in classification.items():
                label = normalize_label(label_raw)
                try:
                    conf = float(conf_raw)
                except (TypeError, ValueError):
                    continue
                if conf < MIN_PRODUCT_CONFIDENCE:
                    continue
                if label in EMPTY_LIKE_LABELS:
                    continue
                if label not in products:
                    continue
                best_conf_by_label[label] = max(best_conf_by_label.get(label, 0.0), conf)

    detected_types = sorted(best_conf_by_label.keys())
    return detected_types, best_conf_by_label


def summarize_detection(
    detected_types: list[str],
    best_conf_by_label: dict[str, float],
    products: dict[str, dict],
) -> tuple[str, str, float, bool, bool, str]:
    """
    Returns:
        normalized_label, display_name, confidence, valid_product, multiple_detected, status_message
    """
    if len(detected_types) >= 2:
        best_conf = max(best_conf_by_label.values()) if best_conf_by_label else 0.0
        return "multiple", "MULTIPLE VEG", best_conf, False, True, "ONE TYPE ONLY"

    if len(detected_types) == 1:
        label = detected_types[0]
        product = products[label]
        return label, str(product["display_name"]), float(best_conf_by_label[label]), True, False, "READY"

    return "none", "NO PRODUCT", 0.0, False, False, "NO PRODUCT"


# =========================================================
# ACTUATOR FUNCTIONS
# =========================================================
def stop_actuator() -> None:
    rpwm.off()
    lpwm.off()


def extend_actuator() -> None:
    rpwm.on()
    lpwm.off()


def retract_actuator() -> None:
    rpwm.off()
    lpwm.on()


def validate_actuator_position(position: str, fallback: str = "extended") -> str:
    normalized = normalize_label(position)
    if normalized not in {"extended", "retracted"}:
        print(f"[WARN] Invalid actuator position '{position}'. Using '{fallback}'.")
        return fallback
    return normalized


def move_actuator_toward_position(position: str, duration_s: float, reason: str = "") -> None:
    """
    Move toward a named end direction for a timed duration.
    Because there is no feedback sensor, this is time-based positioning.
    """
    position = validate_actuator_position(position)
    duration = clamp_time(duration_s)

    if duration <= 0:
        stop_actuator()
        print(f"[ACTUATOR] {reason} No movement because duration is 0.")
        return

    with actuator_lock:
        print(f"[ACTUATOR] Moving toward {position.upper()} for {duration:.2f}s. {reason}")
        if position == "extended":
            extend_actuator()
        else:
            retract_actuator()

        time.sleep(duration)
        stop_actuator()
        print(f"[ACTUATOR] Stopped after moving toward {position.upper()}.")


def move_to_default_position(reason: str = "") -> None:
    default_pos = validate_actuator_position(DEFAULT_POSITION_BEFORE_PRESS)
    move_actuator_toward_position(default_pos, DEFAULT_POSITION_MOVE_TIME_S, reason=reason)


def move_to_after_press_position() -> None:
    after_pos = validate_actuator_position(POSITION_AFTER_PRESS, fallback="retracted")
    move_actuator_toward_position(after_pos, POSITION_AFTER_PRESS_MOVE_TIME_S, reason="Button pressed position.")


def run_sealing_cycle() -> None:
    """
    New requested actuator behavior:
    - Default/no-button state is adjustable, normally maximum EXTENDED.
    - On OK press, actuator moves from default to POSITION_AFTER_PRESS.
    - It holds/pauses.
    - It returns to DEFAULT_POSITION_BEFORE_PRESS.
    """
    print("[ACTION] Starting sealing cycle with adjustable actuator default position...")

    if ENSURE_DEFAULT_BEFORE_EACH_CYCLE:
        move_to_default_position(reason="Ensuring default before sealing cycle.")
        time.sleep(clamp_time(DIR_CHANGE_PAUSE_S))

    move_to_after_press_position()

    stop_actuator()
    time.sleep(clamp_time(PRESS_HOLD_TIME_S))
    time.sleep(clamp_time(RETURN_TO_DEFAULT_DELAY_S))
    time.sleep(clamp_time(DIR_CHANGE_PAUSE_S))

    move_to_default_position(reason="Returning to default after button cycle.")
    stop_actuator()
    print("[ACTION] Sealing cycle complete. Actuator returned to default position.")


# =========================================================
# PRINTER FUNCTIONS
# =========================================================
def print_receipt(snapshot: SystemState) -> None:
    if not PRINTER_ENABLED:
        return

    p: Optional[File] = None
    try:
        with printer_lock:
            p = File(PRINTER_DEVICE)
            p.text("--------------------------\n")
            p.text("VEGETABLE LABEL\n")
            p.text(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
            p.text("--------------------------\n")
            p.text(f"{snapshot.display_name} = PHP {snapshot.price_per_kg:.2f}/KG\n")
            p.text(f"weight: {snapshot.weight_g:.1f} g\n")
            p.text(f"Total Price: PHP {snapshot.total_price:.2f}\n")
            if snapshot.last_transaction_id is not None:
                p.text(f"Txn No: {snapshot.last_transaction_id}\n")
            if snapshot.last_barcode:
                p.text(f"Code: {snapshot.last_barcode}\n\n")
                p.barcode(
                    snapshot.last_barcode,
                    "EAN13",
                    height=BARCODE_HEIGHT,
                    width=BARCODE_WIDTH,
                    pos="BELOW",
                    align_ct=True,
                )
                p.text("\n")
            p.text("--------------------------\n")

            for _ in range(PRINT_FEED_LINES):
                p.text("\n")

            p.close()
            print("[ACTION] Receipt sent to printer.")
    except Exception as e:
        print(f"[ERROR] Printer error: {e}")
        try:
            if p is not None:
                p.close()
        except Exception:
            pass


# =========================================================
# BUTTON ACTION
# =========================================================
def action_worker() -> None:
    with action_lock:
        with state_lock:
            if system_state.busy:
                return
            system_state.busy = True

        try:
            snapshot = capture_snapshot()

            allowed = True
            if not ALLOW_TRIGGER_WITHOUT_VALID_PRODUCT:
                allowed = (
                    snapshot.valid_product
                    and not snapshot.multiple_detected
                    and snapshot.weight_g >= MIN_WEIGHT_TO_ALLOW_PRINT_G
                    and not (BLOCK_PRINT_WHEN_OVERLOAD and snapshot.overloaded)
                )

            if not allowed:
                if BLOCK_PRINT_WHEN_OVERLOAD and snapshot.overloaded:
                    print("[INFO] Button press ignored: load cell overload / remove weight.")
                else:
                    print("[INFO] Button press ignored: no valid single vegetable / insufficient weight.")
                if snapshot.multiple_detected:
                    print("[INFO] Multiple vegetables detected. Please put only one vegetable type at a time.")
                return

            txn_id, barcode = insert_transaction(snapshot)
            snapshot.last_transaction_id = txn_id
            snapshot.last_barcode = barcode

            with state_lock:
                system_state.last_transaction_id = txn_id
                system_state.last_barcode = barcode

            printer_thread = Thread(target=print_receipt, args=(snapshot,), daemon=True)
            printer_thread.start()

            run_sealing_cycle()

            printer_thread.join(timeout=5.0)
        except Exception as e:
            print(f"[ERROR] Action worker failed: {e}")
            stop_actuator()
        finally:
            with state_lock:
                system_state.busy = False


# =========================================================
# MAIN
# =========================================================
def main() -> None:
    print("Starting integrated thesis device...")
    print("Camera + HX711 + LCD + Confirm Button + Tare Button + Actuator + USB Printer + SQLite")
    print("Press Q in preview window to stop.")

    ensure_databases()
    products = fetch_active_vegetables()

    for required_name in ("onion", "garlic", "marble_potato"):
        if required_name not in products:
            print(f"[WARN] '{required_name}' not found or inactive in vegetable_price.db.")

    stop_actuator()
    if MOVE_TO_DEFAULT_ON_STARTUP:
        print("[STARTUP] Moving actuator to DEFAULT_POSITION_BEFORE_PRESS...")
        move_to_default_position(reason="Startup default positioning.")
        stop_actuator()

    offset_raw, scale_raw_per_gram, cal_data, cal_path = load_weight_calibration()
    print(f"[WEIGHT] Calibration loaded from: {cal_path}")
    print(f"[WEIGHT] offset_raw={offset_raw:.2f}, scale_raw_per_gram={scale_raw_per_gram:.8f}")

    hx = SimpleHX711(DT_PIN, SCK_PIN)
    hx.setUnit(Mass.Unit.G)
    warmup_hx711(hx)

    weight_filter = WeightFilterState(
        dynamic_offset_raw=float(offset_raw),
        hard_zero_offset_raw=float(offset_raw),
    )
    weight_status = "MOVING"
    weight_span = 0.0
    gross_weight_g = 0.0
    load_warning = False
    overloaded = False
    load_status = "OK"
    last_weight_console_time = 0.0

    lcd = init_lcd()
    lcd_show(lcd, "System Ready", "Loading model")

    runner = ImageImpulseRunner(MODEL_PATH)
    model_info = runner.init()
    labels = model_info["model_parameters"].get("labels", [])
    print("Model labels:", labels)

    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        # Square capture so preview and inference match your dataset-style view.
        main={"size": (CAPTURE_WIDTH, CAPTURE_HEIGHT), "format": "RGB888"},
        buffer_count=4,
    )
    picam2.configure(config)
    picam2.start()
    time.sleep(CAMERA_WARMUP_SEC)

    base_sensor_crop = get_sensor_square_crop(picam2)
    current_camera_zoom = CAMERA_ZOOM_DEFAULT
    current_camera_zoom, current_scaler_crop = apply_camera_sensor_zoom(
        picam2,
        current_camera_zoom,
        base_sensor_crop,
    )
    print(f"[CAMERA] Default square sensor zoom loaded: {current_camera_zoom:.2f}x")
    print(f"[CAMERA] Base square sensor crop: {base_sensor_crop}")
    print(f"[CAMERA] Current ScalerCrop: {current_scaler_crop}")

    with state_lock:
        system_state.camera_zoom = current_camera_zoom

    lcd_show(lcd, "Camera Ready", "System start")

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, PREVIEW_WIDTH, PREVIEW_HEIGHT)

    last_infer_time = 0.0
    last_weight_time = 0.0
    last_lcd_time = 0.0
    last_lcd_text = ("", "")
    last_console_status = ""
    prev_button_state = False
    prev_tare_button_state = False
    tare_press_start_time: Optional[float] = None

    type_history = deque(maxlen=SMOOTHING_FRAMES)
    conf_history = deque(maxlen=SMOOTHING_FRAMES)

    current_label = "none"
    current_display_name = "NO PRODUCT"
    current_conf = 0.0
    current_valid = False
    current_multiple = False
    current_detected_types: list[str] = []
    current_status_message = "NO PRODUCT"

    try:
        while True:
            now = time.time()
            products = fetch_active_vegetables()

            frame_rgb = picam2.capture_array()
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            if (now - last_infer_time) >= INFER_INTERVAL:
                last_infer_time = now
                model_img = model_view_from_frame(frame_bgr)
                features, _ = runner.get_features_from_image(model_img)
                result = runner.classify(features)

                detected_types, conf_by_label = analyze_inference_result(result, products)
                type_history.append(tuple(detected_types))
                best_conf = max(conf_by_label.values()) if conf_by_label else 0.0
                conf_history.append(best_conf)

                # Smooth the set of detected vegetable types to reduce flicker.
                if type_history:
                    most_common_tuple = Counter(type_history).most_common(1)[0][0]
                    smoothed_types = list(most_common_tuple)
                else:
                    smoothed_types = detected_types

                # Preserve current confidence from latest matching inference.
                smoothed_conf_by_label = {
                    label: conf_by_label.get(label, best_conf)
                    for label in smoothed_types
                }

                (
                    current_label,
                    current_display_name,
                    current_conf,
                    current_valid,
                    current_multiple,
                    current_status_message,
                ) = summarize_detection(smoothed_types, smoothed_conf_by_label, products)
                current_detected_types = smoothed_types

                console_status = f"{current_status_message}|{current_display_name}|{','.join(current_detected_types)}"
                if console_status != last_console_status:
                    if current_multiple:
                        print("[VISION] Multiple vegetables detected. Please put only one vegetable type at a time.")
                        print(f"[VISION] Detected types: {', '.join(current_detected_types)}")
                    elif current_valid:
                        print(f"[VISION] Single vegetable detected: {current_display_name} ({current_conf * 100:.1f}%)")
                    else:
                        print("[VISION] No valid vegetable detected.")
                    last_console_status = console_status

            if (now - last_weight_time) >= WEIGHT_READ_INTERVAL:
                last_weight_time = now
                try:
                    (
                        weight_g,
                        weight_status,
                        weight_span,
                        instant_grams,
                        averaged_grams,
                        raw,
                        gross_weight_g,
                        load_warning,
                        overloaded,
                        load_status,
                    ) = update_weight_filter(hx, weight_filter, scale_raw_per_gram)

                    if (now - last_weight_console_time) >= WEIGHT_CONSOLE_UPDATE_INTERVAL:
                        print(
                            f"[WEIGHT] raw={int(raw):10d} | "
                            f"instant={instant_grams:9.3f} g | "
                            f"average={averaged_grams:9.3f} g | "
                            f"display={format_grams_1_decimal(weight_g):>7} g | "
                            f"span={weight_span:6.3f} | "
                            f"gross={gross_weight_g:9.3f} g | "
                            f"load={load_status} | "
                            f"tare={weight_filter.tare_mode} | "
                            f"{weight_status}"
                        )
                        last_weight_console_time = now

                except Exception as e:
                    print(f"[ERROR] Weight read/filter error: {e}")
                    with state_lock:
                        weight_g = system_state.weight_g
                        weight_status = system_state.weight_status
                        weight_span = system_state.weight_span_g
                        gross_weight_g = system_state.gross_weight_g
                        load_warning = system_state.load_warning
                        overloaded = system_state.overloaded
            else:
                with state_lock:
                    weight_g = system_state.weight_g
                    weight_status = system_state.weight_status
                    weight_span = system_state.weight_span_g
                    gross_weight_g = system_state.gross_weight_g
                    load_warning = system_state.load_warning
                    overloaded = system_state.overloaded

            if current_valid and not current_multiple:
                price_per_kg = float(products[current_label]["price_per_kg"])
                display_name = current_display_name
                total_price = (weight_g / 1000.0) * price_per_kg
                valid_product = True
            else:
                price_per_kg = 0.0
                total_price = 0.0
                display_name = current_display_name
                valid_product = False

            with state_lock:
                system_state.detected_label = current_label
                system_state.display_name = display_name
                system_state.confidence = current_conf
                system_state.camera_zoom = current_camera_zoom
                system_state.weight_g = weight_g
                system_state.weight_status = weight_status
                system_state.weight_span_g = weight_span
                system_state.gross_weight_g = gross_weight_g
                system_state.tare_mode = weight_filter.tare_mode
                system_state.load_warning = load_warning
                system_state.overloaded = overloaded
                system_state.price_per_kg = price_per_kg
                system_state.total_price = total_price
                system_state.valid_product = valid_product
                system_state.multiple_detected = current_multiple
                system_state.detected_types = list(current_detected_types)
                system_state.status_message = current_status_message
                current_state_copy = SystemState(
                    detected_label=system_state.detected_label,
                    display_name=system_state.display_name,
                    confidence=system_state.confidence,
                    camera_zoom=system_state.camera_zoom,
                    weight_g=system_state.weight_g,
                    weight_status=system_state.weight_status,
                    weight_span_g=system_state.weight_span_g,
                    gross_weight_g=system_state.gross_weight_g,
                    tare_mode=system_state.tare_mode,
                    load_warning=system_state.load_warning,
                    overloaded=system_state.overloaded,
                    price_per_kg=system_state.price_per_kg,
                    total_price=system_state.total_price,
                    valid_product=system_state.valid_product,
                    multiple_detected=system_state.multiple_detected,
                    detected_types=list(system_state.detected_types),
                    status_message=system_state.status_message,
                    busy=system_state.busy,
                    last_barcode=system_state.last_barcode,
                    last_transaction_id=system_state.last_transaction_id,
                )

            if (now - last_lcd_time) >= LCD_REFRESH_INTERVAL:
                last_lcd_time = now

                if current_state_copy.busy:
                    line1 = "PROCESSING..."
                    line2 = "Print + Seal"
                elif current_state_copy.overloaded:
                    line1 = "OVERLOAD 8KG"
                    line2 = "REMOVE WEIGHT"
                elif current_state_copy.load_warning:
                    line1 = "NEAR MAX LOAD"
                    line2 = f"Gross:{gross_weight_g:.0f}g"[:16]
                elif current_state_copy.multiple_detected:
                    line1 = "MULTIPLE VEG"
                    line2 = "ONE TYPE ONLY"
                else:
                    line1 = display_name[:16]
                    weight_flag = "S" if weight_status == "STABLE" else "M"
                    line2 = f"{weight_flag}:{weight_g:.1f}g {short_price(total_price)}"[:16]

                if (line1, line2) != last_lcd_text:
                    lcd_show(lcd, line1, line2)
                    last_lcd_text = (line1, line2)

            tare_now = tare_button.is_pressed
            if tare_now and not prev_tare_button_state:
                tare_press_start_time = now
            elif (not tare_now) and prev_tare_button_state:
                press_time = 0.0 if tare_press_start_time is None else now - tare_press_start_time
                if press_time >= TARE_LONG_PRESS_S:
                    apply_hard_zero(weight_filter, scale_raw_per_gram)
                    lcd_show(lcd, "HARD ZERO", "Weight reset")
                else:
                    apply_soft_tare(weight_filter, scale_raw_per_gram)
                    lcd_show(lcd, "SOFT TARE", "Net weight=0")
                tare_press_start_time = None
            prev_tare_button_state = tare_now

            button_now = button.is_pressed
            if button_now and not prev_button_state:
                Thread(target=action_worker, daemon=True).start()
            prev_button_state = button_now

            ui_frame = build_ui_frame(frame_bgr, current_state_copy)
            cv2.imshow(WINDOW_NAME, ui_frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                print("Stopped by user.")
                break
            elif key in (ord("+"), ord("="), ord("d"), ord("D")):
                current_camera_zoom = clamp_zoom(current_camera_zoom + CAMERA_ZOOM_STEP_FINE)
                current_camera_zoom, current_scaler_crop = apply_camera_sensor_zoom(
                    picam2,
                    current_camera_zoom,
                    base_sensor_crop,
                )
                with state_lock:
                    system_state.camera_zoom = current_camera_zoom
                print(f"[CAMERA] Sensor zoom set to {current_camera_zoom:.2f}x | ScalerCrop={current_scaler_crop}")
            elif key in (ord("-"), ord("_"), ord("a"), ord("A")):
                current_camera_zoom = clamp_zoom(current_camera_zoom - CAMERA_ZOOM_STEP_FINE)
                current_camera_zoom, current_scaler_crop = apply_camera_sensor_zoom(
                    picam2,
                    current_camera_zoom,
                    base_sensor_crop,
                )
                with state_lock:
                    system_state.camera_zoom = current_camera_zoom
                print(f"[CAMERA] Sensor zoom set to {current_camera_zoom:.2f}x | ScalerCrop={current_scaler_crop}")
            elif key in (ord("c"), ord("C")):
                current_camera_zoom = clamp_zoom(current_camera_zoom + CAMERA_ZOOM_STEP_COARSE)
                current_camera_zoom, current_scaler_crop = apply_camera_sensor_zoom(
                    picam2,
                    current_camera_zoom,
                    base_sensor_crop,
                )
                with state_lock:
                    system_state.camera_zoom = current_camera_zoom
                print(f"[CAMERA] Sensor zoom set to {current_camera_zoom:.2f}x | ScalerCrop={current_scaler_crop}")
            elif key in (ord("z"), ord("Z")):
                current_camera_zoom = clamp_zoom(current_camera_zoom - CAMERA_ZOOM_STEP_COARSE)
                current_camera_zoom, current_scaler_crop = apply_camera_sensor_zoom(
                    picam2,
                    current_camera_zoom,
                    base_sensor_crop,
                )
                with state_lock:
                    system_state.camera_zoom = current_camera_zoom
                print(f"[CAMERA] Sensor zoom set to {current_camera_zoom:.2f}x | ScalerCrop={current_scaler_crop}")
            elif key in (ord("0"), ord("r"), ord("R")):
                current_camera_zoom = CAMERA_ZOOM_DEFAULT
                current_camera_zoom, current_scaler_crop = apply_camera_sensor_zoom(
                    picam2,
                    current_camera_zoom,
                    base_sensor_crop,
                )
                with state_lock:
                    system_state.camera_zoom = current_camera_zoom
                print(f"[CAMERA] Sensor zoom reset to {current_camera_zoom:.2f}x | ScalerCrop={current_scaler_crop}")

    except KeyboardInterrupt:
        print("Stopped by keyboard interrupt.")

    finally:
        try:
            runner.stop()
        except Exception:
            pass
        try:
            picam2.stop()
        except Exception:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        try:
            lcd_show(lcd, "System stopped", "")
            time.sleep(0.5)
            lcd.close(clear=True)
        except Exception:
            pass

        stop_actuator()
        rpwm.close()
        lpwm.close()
        button.close()
        tare_button.close()


if __name__ == "__main__":
    stop_actuator()
    main()
