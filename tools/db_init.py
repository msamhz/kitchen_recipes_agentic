"""
Initialize the kitchen.db SQLite database with all required tables.
Run once to set up, safe to re-run (CREATE TABLE IF NOT EXISTS).
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "kitchen.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ingredients'")
    fresh = cur.fetchone() is None

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS ingredients (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            in_stock    INTEGER NOT NULL DEFAULT 1,
            last_updated TEXT   NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS recipes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            instructions TEXT    NOT NULL,
            source       TEXT,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            recipe_id     INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
            ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
            is_optional   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (recipe_id, ingredient_id)
        );

        CREATE TABLE IF NOT EXISTS ingredient_aliases (
            alias         TEXT    NOT NULL COLLATE NOCASE,
            ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
            PRIMARY KEY (alias, ingredient_id)
        );
    """)

    # Column migrations — safe to re-run (SQLite has no ADD COLUMN IF NOT EXISTS)
    for sql in [
        "ALTER TABLE recipes ADD COLUMN difficulty TEXT",
        "ALTER TABLE recipes ADD COLUMN prep_time TEXT",
        "ALTER TABLE ingredients ADD COLUMN embedding BLOB",
    ]:
        try:
            cur.execute(sql)
        except Exception:
            pass

    conn.commit()
    conn.close()
    if fresh:
        print(f"[DB] Created new database at: {os.path.abspath(DB_PATH)}")


if __name__ == "__main__":
    init_db()
