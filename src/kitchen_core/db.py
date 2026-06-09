"""
Postgres connection and schema init for Neon deployment.

Run once to create all tables:
    python -c "from kitchen_core.db import init_db; init_db()"
"""

import os

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Add it to .env (see .env.example).")
    return url


def get_connection() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(_get_database_url())
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("CREATE EXTENSION IF NOT EXISTS citext;")
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ingredients (
            id               SERIAL PRIMARY KEY,
            name             CITEXT NOT NULL UNIQUE,
            in_stock         INTEGER NOT NULL DEFAULT 1,
            last_updated     TEXT NOT NULL DEFAULT NOW()::TEXT,
            embedding        BYTEA,  -- TODO B5: migrate to vector(384) for pgvector ANN search
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

    for sql in [
        "ALTER TABLE ingredients ADD COLUMN IF NOT EXISTS expiry_source TEXT",
    ]:
        try:
            cur.execute(sql)
        except Exception:
            pass

    conn.commit()
    conn.close()
    print("[DB] Schema ready on Neon")
