"""
Postgres connection and schema init for Lambda/Neon deployment.

Separate from tools/db_init.py (SQLite) so the local NiceGUI app
keeps working while this branch builds the API layer.

Run once to create all tables in Neon:
    python api/db.py
"""

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]


def get_connection() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # citext gives case-insensitive text columns (replaces SQLite's COLLATE NOCASE)
    cur.execute("CREATE EXTENSION IF NOT EXISTS citext;")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ingredients (
            id               SERIAL PRIMARY KEY,
            name             CITEXT NOT NULL UNIQUE,
            in_stock         INTEGER NOT NULL DEFAULT 1,
            last_updated     TEXT NOT NULL DEFAULT NOW()::TEXT,
            embedding        BYTEA,
            expiry_date      TEXT,
            storage_location TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recipes (
            id           SERIAL PRIMARY KEY,
            name         CITEXT NOT NULL UNIQUE,
            instructions TEXT NOT NULL,
            source       TEXT,
            created_at   TEXT NOT NULL DEFAULT NOW()::TEXT,
            difficulty   TEXT,
            prep_time    TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            recipe_id     INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
            ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
            is_optional   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (recipe_id, ingredient_id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ingredient_aliases (
            alias         CITEXT NOT NULL,
            ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
            PRIMARY KEY (alias, ingredient_id)
        );
    """)

    # Safe column migrations
    for sql in [
        "ALTER TABLE ingredients ADD COLUMN IF NOT EXISTS expiry_source TEXT",
    ]:
        try:
            cur.execute(sql)
        except Exception:
            pass

    conn.commit()
    conn.close()
    print("[DB] Schema ready on Neon (ap-southeast-1)")


if __name__ == "__main__":
    init_db()
