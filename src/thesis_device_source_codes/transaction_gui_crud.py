#!/usr/bin/env python3
"""
Admin CRUD GUI for customer_transactions.db
- View all transactions
- Filter by barcode/product/time
- Select and inspect transaction details
- Add manual transaction for testing/admin work
- Update selected transaction
- Delete selected transaction

The barcode is validated as EAN-13 when manually entered.
"""

from __future__ import annotations

import sqlite3
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

BASE_DIR = Path(__file__).resolve().parent
TXN_DB_PATH = BASE_DIR / "customer_transactions.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(TXN_DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_db() -> None:
    with get_conn() as conn:
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


def ean13_check_digit(first12: str) -> str:
    if len(first12) != 12 or not first12.isdigit():
        raise ValueError("EAN-13 base must be exactly 12 digits.")
    total = 0
    for i, ch in enumerate(first12):
        digit = int(ch)
        total += digit if i % 2 == 0 else digit * 3
    return str((10 - (total % 10)) % 10)


def is_valid_ean13(code: str) -> bool:
    return len(code) == 13 and code.isdigit() and ean13_check_digit(code[:12]) == code[-1]


def create_ean13_from_id(txn_id: int) -> str:
    base12 = f"{txn_id:012d}"
    return base12 + ean13_check_digit(base12)


class TransactionCrudApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Transaction GUI CRUD (Admin)")
        self.root.geometry("1280x680")

        self.filter_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")

        self.id_var = tk.StringVar()
        self.barcode_var = tk.StringVar()
        self.vegetable_name_var = tk.StringVar()
        self.display_name_var = tk.StringVar()
        self.raw_detected_label_var = tk.StringVar()
        self.confidence_var = tk.StringVar()
        self.weight_var = tk.StringVar()
        self.price_per_kg_var = tk.StringVar()
        self.total_price_var = tk.StringVar()
        self.time_var = tk.StringVar()
        self.source_device_var = tk.StringVar(value="raspberry_pi_4_offline")

        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)

        top = ttk.Frame(outer)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Filter:").pack(side="left")
        filter_entry = ttk.Entry(top, textvariable=self.filter_var, width=36)
        filter_entry.pack(side="left", padx=(4, 8))
        filter_entry.bind("<KeyRelease>", lambda _e: self.refresh())
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(top, text="Clear Form", command=self.clear_form).pack(side="left", padx=8)
        ttk.Button(top, text="Add Manual Transaction", command=self.add_transaction).pack(side="left")
        ttk.Button(top, text="Update Selected", command=self.update_selected).pack(side="left", padx=8)
        ttk.Button(top, text="Delete Selected", command=self.delete_selected).pack(side="left")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        content = ttk.Panedwindow(outer, orient="horizontal")
        content.pack(fill="both", expand=True)

        left = ttk.Frame(content, padding=4)
        right = ttk.Frame(content, padding=8)
        content.add(left, weight=3)
        content.add(right, weight=2)

        columns = (
            "id", "barcode_ean13", "vegetable_display_name", "weight_g",
            "price_per_kg", "total_price", "transaction_time"
        )
        self.tree = ttk.Treeview(left, columns=columns, show="headings", height=24)
        self.tree.pack(fill="both", expand=True)

        headings = {
            "id": "ID",
            "barcode_ean13": "Barcode",
            "vegetable_display_name": "Product",
            "weight_g": "Weight (g)",
            "price_per_kg": "Price/KG",
            "total_price": "Total",
            "transaction_time": "Time",
        }
        widths = {
            "id": 55,
            "barcode_ean13": 150,
            "vegetable_display_name": 160,
            "weight_g": 90,
            "price_per_kg": 90,
            "total_price": 90,
            "transaction_time": 180,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="center")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        form = ttk.LabelFrame(right, text="Transaction Form", padding=10)
        form.pack(fill="both", expand=True)

        fields = [
            ("Transaction ID", self.id_var, True),
            ("Barcode EAN13", self.barcode_var, False),
            ("Vegetable Name", self.vegetable_name_var, False),
            ("Display Name", self.display_name_var, False),
            ("Raw Detected Label", self.raw_detected_label_var, False),
            ("Confidence (0-1)", self.confidence_var, False),
            ("Weight (g)", self.weight_var, False),
            ("Price per KG", self.price_per_kg_var, False),
            ("Total Price", self.total_price_var, False),
            ("Transaction Time", self.time_var, False),
            ("Source Device", self.source_device_var, False),
        ]

        self.entries: dict[str, ttk.Entry] = {}
        for row_index, (label, var, readonly) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row_index, column=0, sticky="w", padx=4, pady=4)
            state = "readonly" if readonly else "normal"
            entry = ttk.Entry(form, textvariable=var, width=34, state=state)
            entry.grid(row=row_index, column=1, sticky="ew", padx=4, pady=4)
            self.entries[label] = entry

        form.columnconfigure(1, weight=1)
        self.refresh()

    def clear_form(self) -> None:
        self.id_var.set("")
        self.barcode_var.set("")
        self.vegetable_name_var.set("")
        self.display_name_var.set("")
        self.raw_detected_label_var.set("")
        self.confidence_var.set("")
        self.weight_var.set("")
        self.price_per_kg_var.set("")
        self.total_price_var.set("")
        self.time_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.source_device_var.set("raspberry_pi_4_offline")
        self.tree.selection_remove(self.tree.selection())
        self.status_var.set("Form cleared.")

    def selected_id(self) -> int | None:
        selected = self.tree.selection()
        if not selected:
            return None
        values = self.tree.item(selected[0], "values")
        return int(values[0])

    def refresh(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        q = self.filter_var.get().strip().lower()
        with get_conn() as conn:
            if q:
                rows = conn.execute(
                    """
                    SELECT id, barcode_ean13, vegetable_display_name, weight_g,
                           price_per_kg, total_price, transaction_time
                    FROM customer_transactions
                    WHERE lower(barcode_ean13) LIKE ?
                       OR lower(vegetable_display_name) LIKE ?
                       OR lower(transaction_time) LIKE ?
                    ORDER BY id DESC
                    """,
                    (f"%{q}%", f"%{q}%", f"%{q}%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, barcode_ean13, vegetable_display_name, weight_g,
                           price_per_kg, total_price, transaction_time
                    FROM customer_transactions
                    ORDER BY id DESC
                    """
                ).fetchall()

        for row in rows:
            self.tree.insert(
                "",
                "end",
                values=(
                    row["id"],
                    row["barcode_ean13"],
                    row["vegetable_display_name"],
                    f"{row['weight_g']:.2f}",
                    f"{row['price_per_kg']:.2f}",
                    f"{row['total_price']:.2f}",
                    row["transaction_time"],
                ),
            )

        self.status_var.set(f"Loaded {len(rows)} transaction(s).")

    def on_select(self, _event=None) -> None:
        row_id = self.selected_id()
        if row_id is None:
            return

        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT id, barcode_ean13, vegetable_name, vegetable_display_name,
                       raw_detected_label, confidence, weight_g, price_per_kg,
                       total_price, transaction_time, source_device
                FROM customer_transactions
                WHERE id = ?
                """,
                (row_id,),
            ).fetchone()

        if row is None:
            return

        self.id_var.set(str(row["id"]))
        self.barcode_var.set(row["barcode_ean13"])
        self.vegetable_name_var.set(row["vegetable_name"])
        self.display_name_var.set(row["vegetable_display_name"])
        self.raw_detected_label_var.set(row["raw_detected_label"])
        self.confidence_var.set(str(row["confidence"]))
        self.weight_var.set(f"{row['weight_g']:.2f}")
        self.price_per_kg_var.set(f"{row['price_per_kg']:.2f}")
        self.total_price_var.set(f"{row['total_price']:.2f}")
        self.time_var.set(row["transaction_time"])
        self.source_device_var.set(row["source_device"])
        self.status_var.set(f"Selected transaction ID {row['id']}")

    def parse_numbers(self) -> tuple[float, float, float, float] | None:
        try:
            confidence = float(self.confidence_var.get().strip())
            weight_g = float(self.weight_var.get().strip())
            price_per_kg = float(self.price_per_kg_var.get().strip())
            total_price = float(self.total_price_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid number", "Confidence, weight, price, and total must be valid numbers.")
            return None

        if not (0.0 <= confidence <= 1.0):
            messagebox.showerror("Invalid confidence", "Confidence must be between 0 and 1.")
            return None
        if weight_g < 0 or price_per_kg < 0 or total_price < 0:
            messagebox.showerror("Invalid value", "Weight, price, and total cannot be negative.")
            return None

        return confidence, weight_g, price_per_kg, total_price

    def validate_barcode(self, code: str) -> bool:
        if not code:
            return True
        if not is_valid_ean13(code):
            messagebox.showerror("Invalid barcode", "Barcode must be a valid 13-digit EAN-13 value.")
            return False
        return True

    def add_transaction(self) -> None:
        vegetable_name = self.vegetable_name_var.get().strip().lower().replace(" ", "_")
        display_name = self.display_name_var.get().strip()
        raw_detected_label = self.raw_detected_label_var.get().strip() or vegetable_name
        barcode = self.barcode_var.get().strip()
        transaction_time = self.time_var.get().strip() or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source_device = self.source_device_var.get().strip() or "raspberry_pi_4_offline"

        if not vegetable_name or not display_name:
            messagebox.showwarning("Missing fields", "Vegetable name and display name are required.")
            return

        parsed = self.parse_numbers()
        if parsed is None:
            return
        confidence, weight_g, price_per_kg, total_price = parsed

        if barcode and not self.validate_barcode(barcode):
            return

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if barcode:
                    cur.execute(
                        """
                        INSERT INTO customer_transactions (
                            barcode_ean13, vegetable_name, vegetable_display_name,
                            raw_detected_label, confidence, weight_g, price_per_kg,
                            total_price, transaction_time, source_device
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            barcode, vegetable_name, display_name, raw_detected_label,
                            confidence, weight_g, price_per_kg, total_price,
                            transaction_time, source_device,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO customer_transactions (
                            barcode_ean13, vegetable_name, vegetable_display_name,
                            raw_detected_label, confidence, weight_g, price_per_kg,
                            total_price, transaction_time, source_device
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "PENDING", vegetable_name, display_name, raw_detected_label,
                            confidence, weight_g, price_per_kg, total_price,
                            transaction_time, source_device,
                        ),
                    )
                    row_id = int(cur.lastrowid)
                    barcode = create_ean13_from_id(row_id)
                    cur.execute(
                        "UPDATE customer_transactions SET barcode_ean13 = ? WHERE id = ?",
                        (barcode, row_id),
                    )
                conn.commit()
        except sqlite3.IntegrityError:
            messagebox.showerror("Duplicate barcode", "That barcode already exists in the database.")
            return

        self.status_var.set("Manual transaction added.")
        self.refresh()

    def update_selected(self) -> None:
        row_id = self.selected_id()
        if row_id is None:
            messagebox.showwarning("No selection", "Select a transaction first.")
            return

        vegetable_name = self.vegetable_name_var.get().strip().lower().replace(" ", "_")
        display_name = self.display_name_var.get().strip()
        raw_detected_label = self.raw_detected_label_var.get().strip() or vegetable_name
        barcode = self.barcode_var.get().strip()
        transaction_time = self.time_var.get().strip()
        source_device = self.source_device_var.get().strip() or "raspberry_pi_4_offline"

        if not vegetable_name or not display_name or not transaction_time:
            messagebox.showwarning("Missing fields", "Complete all required fields first.")
            return

        parsed = self.parse_numbers()
        if parsed is None:
            return
        confidence, weight_g, price_per_kg, total_price = parsed

        if not self.validate_barcode(barcode):
            return

        try:
            with get_conn() as conn:
                conn.execute(
                    """
                    UPDATE customer_transactions
                    SET barcode_ean13 = ?,
                        vegetable_name = ?,
                        vegetable_display_name = ?,
                        raw_detected_label = ?,
                        confidence = ?,
                        weight_g = ?,
                        price_per_kg = ?,
                        total_price = ?,
                        transaction_time = ?,
                        source_device = ?
                    WHERE id = ?
                    """,
                    (
                        barcode,
                        vegetable_name,
                        display_name,
                        raw_detected_label,
                        confidence,
                        weight_g,
                        price_per_kg,
                        total_price,
                        transaction_time,
                        source_device,
                        row_id,
                    ),
                )
                conn.commit()
        except sqlite3.IntegrityError:
            messagebox.showerror("Duplicate barcode", "That barcode already exists in another transaction.")
            return

        self.status_var.set(f"Updated transaction ID {row_id}")
        self.refresh()

    def delete_selected(self) -> None:
        row_id = self.selected_id()
        if row_id is None:
            messagebox.showwarning("No selection", "Select a transaction first.")
            return

        answer = messagebox.askyesno(
            "Confirm delete",
            "Delete the selected transaction from customer_transactions.db?\n\nThis action cannot be undone.",
        )
        if not answer:
            return

        with get_conn() as conn:
            conn.execute("DELETE FROM customer_transactions WHERE id = ?", (row_id,))
            conn.commit()

        self.status_var.set(f"Deleted transaction ID {row_id}")
        self.clear_form()
        self.refresh()


def main() -> None:
    ensure_db()
    root = tk.Tk()
    app = TransactionCrudApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
