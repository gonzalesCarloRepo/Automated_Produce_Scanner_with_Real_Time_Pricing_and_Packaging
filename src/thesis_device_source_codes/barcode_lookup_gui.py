#!/usr/bin/env python3
"""
Barcode transaction lookup GUI for Raspberry Pi.

Supports two input methods:
1) USB barcode scanner through evdev (/dev/input/event8)
2) Keyboard wedge/manual typing into the focused entry box

Behavior:
- The entry box is focused on startup and after every scan/search.
- If a barcode is found in customer_transactions.db, the GUI shows a
  receipt-like format matching the printed receipt style.
- If the barcode is not found, the GUI clearly says so and waits for another scan.
"""

from __future__ import annotations

import sqlite3
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from evdev import InputDevice, categorize, ecodes

#BASE_DIR = Path(__file__).resolve().parent
# = BASE_DIR / 
DEFAULT_TXN_DB_PATH = "/home/jekaca/Thesis/final_device_3.1/customer_transactions.db"
KNOWN_TXN_DB_PATH = Path("/home/jekaca/Thesis/final_device_3.1/customer_transactions.db")
TXN_DB_PATH = KNOWN_TXN_DB_PATH if KNOWN_TXN_DB_PATH.exists() else DEFAULT_TXN_DB_PATH

SCANNER_DEVICE = "/dev/input/event8"

KEYMAP = {
    "KEY_1": "1", "KEY_2": "2", "KEY_3": "3", "KEY_4": "4", "KEY_5": "5",
    "KEY_6": "6", "KEY_7": "7", "KEY_8": "8", "KEY_9": "9", "KEY_0": "0",
}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(TXN_DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def lookup_barcode(barcode: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, barcode_ean13, vegetable_display_name, weight_g,
                   price_per_kg, total_price, confidence, transaction_time
            FROM customer_transactions
            WHERE barcode_ean13 = ?
            """,
            (barcode,),
        ).fetchone()
    return row


def build_receipt_text(row: sqlite3.Row) -> str:
    return (
        "--------------------------\n"
        "VEGETABLE LABEL\n"
        f"{row['transaction_time']}\n"
        "--------------------------\n"
        f"{row['vegetable_display_name']} = PHP {row['price_per_kg']:.2f}/KG\n"
        f"weight: {row['weight_g']:.2f} g\n"
        f"Total Price: PHP {row['total_price']:.2f}\n"
        f"Txn No: {row['id']}\n"
        f"Code: {row['barcode_ean13']}\n"
        f"Confidence: {row['confidence'] * 100:.1f}%\n"
        "--------------------------\n"
    )


class BarcodeLookupApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Barcode Transaction Lookup")
        self.root.geometry("620x520")

        self.scanned_value = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Waiting for scanner or manual input...")
        self.evdev_connected = False
        self.entry_buffer = ""

        main = ttk.Frame(root, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Scanned Barcode", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.entry = ttk.Entry(main, textvariable=self.scanned_value, font=("TkDefaultFont", 14))
        self.entry.pack(fill="x", pady=(4, 10))
        self.entry.bind("<Return>", lambda _e: self.manual_search())

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=(0, 10))
        ttk.Button(buttons, text="Search", command=self.manual_search).pack(side="left")
        ttk.Button(buttons, text="Clear", command=self.clear_all).pack(side="left", padx=8)

        ttk.Label(main, textvariable=self.status_text).pack(anchor="w", pady=(0, 12))

        self.text = tk.Text(main, height=20, wrap="word", font=("Courier New", 11))
        self.text.pack(fill="both", expand=True)
        self.text.insert(tk.END, "Ready to scan...\n")
        self.text.config(state="disabled")

        self.entry.focus_set()
        self.root.after(200, self.refocus_entry)

        threading.Thread(target=self.scanner_loop, daemon=True).start()

    def refocus_entry(self) -> None:
        try:
            self.entry.focus_force()
            self.entry.icursor(tk.END)
        except Exception:
            pass
        self.root.after(500, self.refocus_entry)

    def set_text(self, content: str) -> None:
        self.text.config(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, content)
        self.text.config(state="disabled")

    def show_result(self, row: sqlite3.Row | None, barcode: str) -> None:
        if row is None:
            self.status_text.set("Transaction not found. Ready for another scan.")
            self.set_text(
                "--------------------------\n"
                f"Code: {barcode}\n"
                "Transaction is not in the database.\n"
                "Please scan another barcode.\n"
                "--------------------------\n"
            )
            self.entry.selection_range(0, tk.END)
            return

        self.status_text.set("Transaction found.")
        self.set_text(build_receipt_text(row))
        self.entry.selection_range(0, tk.END)

    def process_barcode(self, barcode: str) -> None:
        barcode = barcode.strip()
        if not barcode:
            self.status_text.set("No barcode value received.")
            return

        self.scanned_value.set(barcode)
        row = lookup_barcode(barcode)
        self.show_result(row, barcode)
        self.entry.focus_set()
        self.entry.icursor(tk.END)

    def manual_search(self) -> None:
        barcode = self.scanned_value.get().strip()
        if not barcode:
            messagebox.showwarning("Missing barcode", "No barcode value is currently available.")
            self.entry.focus_set()
            return
        self.process_barcode(barcode)

    def clear_all(self) -> None:
        self.scanned_value.set("")
        self.status_text.set("Waiting for scanner or manual input...")
        self.set_text("Ready to scan...\n")
        self.entry.focus_set()

    def scanner_loop(self) -> None:
        try:
            device = InputDevice(SCANNER_DEVICE)
            self.evdev_connected = True
            self.root.after(0, lambda: self.status_text.set(f"Scanner connected: {device.name} ({SCANNER_DEVICE})"))

            barcode = ""
            for event in device.read_loop():
                if event.type != ecodes.EV_KEY:
                    continue

                key_event = categorize(event)
                if key_event.keystate != 1:
                    continue

                key = key_event.keycode
                if isinstance(key, list):
                    key = key[0]

                if key == "KEY_ENTER":
                    scanned = barcode
                    barcode = ""
                    if scanned:
                        self.root.after(0, lambda b=scanned: self.process_barcode(b))
                elif key in KEYMAP:
                    barcode += KEYMAP[key]
                    self.root.after(0, lambda b=barcode: self.scanned_value.set(b))

        except Exception as e:
            self.evdev_connected = False
            self.root.after(
                0,
                lambda: self.status_text.set(
                    f"evdev scanner unavailable: {e}. Keyboard/manual entry is still ready."
                ),
            )


def main() -> None:
    root = tk.Tk()
    app = BarcodeLookupApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

