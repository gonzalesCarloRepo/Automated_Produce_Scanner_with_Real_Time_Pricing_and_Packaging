#!/usr/bin/env python3
"""
Admin CRUD GUI for vegetable_price.db
- Add vegetable
- Update selected vegetable
- Toggle active/inactive
- Delete selected vegetable
- Refresh and simple filter

Designed for easy debugging and modification on Raspberry Pi.
"""

from __future__ import annotations

import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

BASE_DIR = Path(__file__).resolve().parent
VEG_DB_PATH = BASE_DIR / "vegetable_price.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(VEG_DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_db() -> None:
    with get_conn() as conn:
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


class VegetableCrudApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Vegetable GUI CRUD (Admin)")
        self.root.geometry("900x520")

        self.name_var = tk.StringVar()
        self.display_name_var = tk.StringVar()
        self.price_var = tk.StringVar()
        self.filter_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")

        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)

        form = ttk.LabelFrame(outer, text="Vegetable Form", padding=10)
        form.pack(fill="x")

        ttk.Label(form, text="Internal Name").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.name_entry = ttk.Entry(form, textvariable=self.name_var, width=24)
        self.name_entry.grid(row=0, column=1, sticky="w", padx=4, pady=4)

        ttk.Label(form, text="Display Name").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        ttk.Entry(form, textvariable=self.display_name_var, width=24).grid(row=0, column=3, sticky="w", padx=4, pady=4)

        ttk.Label(form, text="Price / KG").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(form, textvariable=self.price_var, width=24).grid(row=1, column=1, sticky="w", padx=4, pady=4)

        ttk.Button(form, text="Add Vegetable", command=self.add_vegetable).grid(row=1, column=2, padx=4, pady=4)
        ttk.Button(form, text="Update Selected", command=self.update_selected).grid(row=1, column=3, padx=4, pady=4)

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(10, 8))

        ttk.Label(controls, text="Filter:").pack(side="left")
        filter_entry = ttk.Entry(controls, textvariable=self.filter_var, width=24)
        filter_entry.pack(side="left", padx=(4, 8))
        filter_entry.bind("<KeyRelease>", lambda _e: self.refresh())

        ttk.Button(controls, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(controls, text="Clear Form", command=self.clear_form).pack(side="left", padx=8)
        ttk.Button(controls, text="Toggle Active", command=self.toggle_active).pack(side="left")
        ttk.Button(controls, text="Delete Selected", command=self.delete_selected).pack(side="left", padx=8)
        ttk.Label(controls, textvariable=self.status_var).pack(side="right")

        columns = ("id", "name", "display_name", "price_per_kg", "is_active", "updated_at")
        self.tree = ttk.Treeview(outer, columns=columns, show="headings", height=16)
        self.tree.pack(fill="both", expand=True)

        headings = {
            "id": "ID",
            "name": "Internal Name",
            "display_name": "Display Name",
            "price_per_kg": "Price / KG",
            "is_active": "Active",
            "updated_at": "Updated At",
        }
        widths = {
            "id": 55,
            "name": 150,
            "display_name": 180,
            "price_per_kg": 110,
            "is_active": 75,
            "updated_at": 180,
        }

        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="center")

        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.refresh()
        self.name_entry.focus_set()

    def clear_form(self) -> None:
        self.name_var.set("")
        self.display_name_var.set("")
        self.price_var.set("")
        self.tree.selection_remove(self.tree.selection())
        self.status_var.set("Form cleared.")
        self.name_entry.focus_set()

    def refresh(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        search = self.filter_var.get().strip().lower()
        with get_conn() as conn:
            if search:
                rows = conn.execute(
                    """
                    SELECT id, name, display_name, price_per_kg, is_active, updated_at
                    FROM vegetables
                    WHERE lower(name) LIKE ? OR lower(display_name) LIKE ?
                    ORDER BY name
                    """,
                    (f"%{search}%", f"%{search}%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, name, display_name, price_per_kg, is_active, updated_at
                    FROM vegetables
                    ORDER BY name
                    """
                ).fetchall()

        for row in rows:
            self.tree.insert(
                "",
                "end",
                values=(
                    row["id"],
                    row["name"],
                    row["display_name"],
                    f"{row['price_per_kg']:.2f}",
                    row["is_active"],
                    row["updated_at"],
                ),
            )

        self.status_var.set(f"Loaded {len(rows)} vegetable(s).")

    def selected_id(self) -> int | None:
        selected = self.tree.selection()
        if not selected:
            return None
        values = self.tree.item(selected[0], "values")
        return int(values[0])

    def on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return

        values = self.tree.item(selected[0], "values")
        self.name_var.set(values[1])
        self.display_name_var.set(values[2])
        self.price_var.set(values[3])
        self.status_var.set(f"Selected vegetable ID {values[0]}")

    def parse_price(self) -> float | None:
        price_text = self.price_var.get().strip()
        try:
            price = float(price_text)
            if price < 0:
                raise ValueError
            return price
        except ValueError:
            messagebox.showerror("Invalid price", "Price per kilogram must be a non-negative number.")
            return None

    def add_vegetable(self) -> None:
        name = self.name_var.get().strip().lower().replace(" ", "_")
        display_name = self.display_name_var.get().strip()
        price = self.parse_price()

        if not name or not display_name or price is None:
            if not name or not display_name:
                messagebox.showwarning("Missing fields", "Please complete all fields.")
            return

        try:
            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO vegetables (name, display_name, price_per_kg, is_active)
                    VALUES (?, ?, ?, 1)
                    """,
                    (name, display_name, price),
                )
                conn.commit()
            self.status_var.set(f"Added vegetable: {name}")
            self.refresh()
        except sqlite3.IntegrityError:
            messagebox.showerror("Duplicate name", "That internal vegetable name already exists.")

    def update_selected(self) -> None:
        row_id = self.selected_id()
        if row_id is None:
            messagebox.showwarning("No selection", "Select a vegetable first.")
            return

        name = self.name_var.get().strip().lower().replace(" ", "_")
        display_name = self.display_name_var.get().strip()
        price = self.parse_price()

        if not name or not display_name or price is None:
            if not name or not display_name:
                messagebox.showwarning("Missing fields", "Please complete all fields.")
            return

        try:
            with get_conn() as conn:
                conn.execute(
                    """
                    UPDATE vegetables
                    SET name = ?, display_name = ?, price_per_kg = ?
                    WHERE id = ?
                    """,
                    (name, display_name, price, row_id),
                )
                conn.commit()
            self.status_var.set(f"Updated vegetable ID {row_id}")
            self.refresh()
        except sqlite3.IntegrityError:
            messagebox.showerror("Duplicate name", "Another vegetable already uses that internal name.")

    def toggle_active(self) -> None:
        row_id = self.selected_id()
        if row_id is None:
            messagebox.showwarning("No selection", "Select a vegetable first.")
            return

        with get_conn() as conn:
            row = conn.execute("SELECT is_active FROM vegetables WHERE id = ?", (row_id,)).fetchone()
            if row is None:
                messagebox.showerror("Missing row", "Selected row no longer exists.")
                return

            new_value = 0 if int(row["is_active"]) == 1 else 1
            conn.execute("UPDATE vegetables SET is_active = ? WHERE id = ?", (new_value, row_id))
            conn.commit()

        self.status_var.set(f"Toggled active state for ID {row_id}")
        self.refresh()

    def delete_selected(self) -> None:
        row_id = self.selected_id()
        if row_id is None:
            messagebox.showwarning("No selection", "Select a vegetable first.")
            return

        answer = messagebox.askyesno(
            "Confirm delete",
            "Delete the selected vegetable from vegetable_price.db?\n\nThis action cannot be undone.",
        )
        if not answer:
            return

        with get_conn() as conn:
            conn.execute("DELETE FROM vegetables WHERE id = ?", (row_id,))
            conn.commit()

        self.status_var.set(f"Deleted vegetable ID {row_id}")
        self.clear_form()
        self.refresh()


def main() -> None:
    ensure_db()
    root = tk.Tk()
    app = VegetableCrudApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
