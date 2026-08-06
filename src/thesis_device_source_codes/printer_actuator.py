#!/usr/bin/env python3
"""
Raspberry Pi 4 + BTS7960 + 12V Linear Actuator + USB Thermal Printer
One active-HIGH button triggers:
1) sealing cycle
2) print "SEALING DONE"

GPIO:
- GPIO17 = button input
- GPIO23 = RPWM
- GPIO24 = LPWM
"""

from __future__ import annotations

from signal import pause
from threading import Lock, Thread
from time import sleep, strftime

from escpos.printer import File
from gpiozero import Button, DigitalOutputDevice

# -----------------------------
# GPIO (BCM numbering)
# -----------------------------
BTN_PIN = 17
RPWM_PIN = 23
LPWM_PIN = 24

# -----------------------------
# Actuator timing (EDIT THESE)
# -----------------------------
# Distance is controlled indirectly by time because there is no feedback sensor.
EXTEND_TIME_S = 2.50
PRESS_HOLD_TIME_S = 0.80
RETRACT_DELAY_S = 0.00
RETRACT_TIME_S = 2.50
DIR_CHANGE_PAUSE_S = 0.20

# -----------------------------
# Button config
# -----------------------------
BUTTON_BOUNCE_S = 0.04

# -----------------------------
# Printer config
# -----------------------------
PRINTER_ENABLED = True
PRINTER_DEVICE = "/dev/usb/lp0"
PRINT_FEED_LINES = 3

# -----------------------------
# Initialize GPIO devices
# -----------------------------
rpwm = DigitalOutputDevice(RPWM_PIN, active_high=True, initial_value=False)
lpwm = DigitalOutputDevice(LPWM_PIN, active_high=True, initial_value=False)
button = Button(BTN_PIN, pull_up=False, bounce_time=BUTTON_BOUNCE_S)

busy = False
printer_lock = Lock()


# -----------------------------
# Actuator functions
# -----------------------------
def stop_actuator() -> None:
    rpwm.off()
    lpwm.off()


def extend_actuator() -> None:
    rpwm.on()
    lpwm.off()


def retract_actuator() -> None:
    rpwm.off()
    lpwm.on()


# -----------------------------
# Printer function
# -----------------------------
def print_sealing_done() -> None:
    if not PRINTER_ENABLED:
        return

    p = None
    try:
        with printer_lock:
            p = File(PRINTER_DEVICE)
            p.text("SEALING DONE\n")
            p.text(strftime("%Y-%m-%d %H:%M:%S") + "\n")
            for _ in range(PRINT_FEED_LINES):
                p.text("\n")
            p.close()
            print("Printer: 'SEALING DONE' sent.")
    except Exception as e:
        print(f"Printer error: {e}")
        try:
            if p is not None:
                p.close()
        except Exception:
            pass


# -----------------------------
# Sealing cycle
# -----------------------------
def run_sealing_cycle() -> None:
    print("Button pressed. Starting sealing cycle...")

    extend_actuator()
    sleep(EXTEND_TIME_S)

    stop_actuator()
    sleep(PRESS_HOLD_TIME_S)
    sleep(RETRACT_DELAY_S)
    sleep(DIR_CHANGE_PAUSE_S)

    retract_actuator()
    sleep(RETRACT_TIME_S)

    stop_actuator()
    print("Sealing cycle complete.")


# -----------------------------
# Button event
# -----------------------------
def on_press() -> None:
    global busy

    if busy:
        return

    busy = True
    try:
        Thread(target=print_sealing_done, daemon=True).start()
        run_sealing_cycle()

        while button.is_pressed:
            sleep(0.01)
    finally:
        busy = False


# -----------------------------
# Main
# -----------------------------
stop_actuator()
print("Ready. Press the confirmation/sealing button.")
button.when_pressed = on_press

try:
    pause()
except KeyboardInterrupt:
    pass
finally:
    stop_actuator()
    rpwm.close()
    lpwm.close()
    button.close()
