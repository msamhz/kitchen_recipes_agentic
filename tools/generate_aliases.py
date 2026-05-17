"""
Ingredient Alias Generator
---------------------------
For each ingredient in the DB, uses Claude in parallel batches to generate
simple keyword aliases (e.g. "spaghetti" for "spaghetti / durum wheat pasta").
Stored in ingredient_aliases so match_recipes can do fuzzy name matching.

Usage:
    python tools/generate_aliases.py              # all ingredients
    python tools/generate_aliases.py --new-only   # only those without aliases yet
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from db_init import get_connection, init_db
from clients import async_client

BATCH_PROMPT = """You are normalizing ingredient names for a kitchen inventory system.

For each ingredient listed below, generate simple common alternative names or keywords
that refer to the SAME ingredient (not different ones).

Ingredients:
{items}

Rules:
- Always include the simplest base name (e.g. "spaghetti" for "spaghetti / durum wheat pasta")
- Include the original name itself as an alias
- Include common short forms, abbreviations, and alternative spellings
- Do NOT add aliases for different ingredients (e.g. don't alias "linguine" under "spaghetti")
- Lowercase only, 1-5 words per alias

Return ONLY valid JSON, no markdown:
{{
  "results": [
    {{"id": <ingredient_id>, "aliases": ["alias1", "alias2"]}},
    ...
  ]
}}"""


async def _generate_batch(batch: list[dict]) -> list[dict]:
    items_text = "\n".join(f"- id={row['id']}: {row['name']}" for row in batch)
    response = await async_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": BATCH_PROMPT.format(items=items_text)}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw.strip()).get("results", [])
    except json.JSONDecodeError:
        return []


def _upsert_aliases(results: list[dict]):
    conn = get_connection()
    cur = conn.cursor()
    for item in results:
        ing_id = item.get("id")
        if ing_id is None:
            continue
        for alias in item.get("aliases", []):
            alias = alias.strip().lower()
            if alias:
                cur.execute(
                    "INSERT INTO ingredient_aliases (alias, ingredient_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                    (alias, ing_id),
                )
    conn.commit()
    conn.close()


async def run_async(new_only: bool = False):
    conn = get_connection()
    cur = conn.cursor()
    if new_only:
        cur.execute("""
            SELECT id, name FROM ingredients
            WHERE id NOT IN (SELECT DISTINCT ingredient_id FROM ingredient_aliases)
            ORDER BY id
        """)
    else:
        cur.execute("SELECT id, name FROM ingredients ORDER BY id")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not rows:
        print("[Aliases] Nothing to process.")
        return

    BATCH_SIZE = 10
    CONCURRENCY = 4
    batches = [rows[i:i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]
    print(f"[Aliases] Generating for {len(rows)} ingredient(s) in {len(batches)} batch(es)...")

    for i in range(0, len(batches), CONCURRENCY):
        group = batches[i:i + CONCURRENCY]
        results_list = await asyncio.gather(*[_generate_batch(b) for b in group])
        for results in results_list:
            _upsert_aliases(results)

    print("[Aliases] Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingredient Alias Generator")
    parser.add_argument("--new-only", action="store_true", help="Only process ingredients with no aliases yet")
    args = parser.parse_args()
    init_db()
    asyncio.run(run_async(new_only=args.new_only))
