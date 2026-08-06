#!/usr/bin/env python3
"""
Initialize the two SQLite databases used by the thesis device.
"""

from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
VEG_DB_PATH = BASE_DIR / "vegetable_price.db"
TXN_DB_PATH = BASE_DIR / "customer_transactions.db"

DEFAULT_VEGETABLES = [
    ("onion", "ONION", 100.0, 1),
    ("garlic", "GARLIC", 180.0, 1),
    ("marble_potato", "MARBLE POTATO", 120.0, 1),
]


def get_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def main() -> None:
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

        for row in DEFAULT_VEGETABLES:
            conn.execute(
                """
                INSERT INTO vegetables (name, display_name, price_per_kg, is_active)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO NOTHING
                """,
                row,
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_transactions_barcode ON customer_transactions(barcode_ean13)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_transactions_time ON customer_transactions(transaction_time)")
        conn.commit()

    print("Databases initialized successfully.")
    print(f"Vegetable DB: {VEG_DB_PATH}")
    print(f"Transaction DB: {TXN_DB_PATH}")


if __name__ == "__main__":
    main()
