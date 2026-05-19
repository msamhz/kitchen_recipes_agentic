"""
Ingredient Normaliser
----------------------
Before any DB write, resolves a new ingredient name to a canonical form:
- Merges plurals  (egg → eggs if "eggs" already in DB)
- Merges multilingual variants  (kicap lemak manis → sweet soy sauce)
- Merges brand variants  (mahsuri kicap lemak manis → kicap manis)
- Keeps genuinely distinct ingredients separate

Uses Haiku for cost-efficiency (simple classification task).
Validates the returned name before accepting a merge.

Usage (cleanup pass):
    python tools/normalise.py --dry-run    # preview merges without writing
    python tools/normalise.py              # apply merges to kitchen.db
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from db_init import get_connection
from clients import sync_client, async_client

NORMALISE_PROMPT = """You are a kitchen ingredient normaliser for a recipe app used in Singapore.

New ingredient to check: "{name}"

Existing ingredients in the database:
{existing}

Your task:
- If the new ingredient is CLEARLY the same physical ingredient as an existing one, return the EXISTING name.
- Consider these cases as matches:
  * Plurals: "egg" and "eggs", "potato" and "potatoes"
  * Multilingual equivalents: "kicap lemak manis" = "sweet soy sauce", "bawang putih" = "garlic"
  * Brand + generic: "mahsuri kicap lemak manis" → "kicap manis", "tai hua soy sauce" → "soy sauce"
  * Minor spelling/spacing: "soy sauce" and "soysauce"
  * Abbreviations: "msg" = "monosodium glutamate"
- Only merge when HIGHLY confident — different spices/sauces that share a word are NOT the same
- If no match or you are uncertain, return the new ingredient name cleaned up (lowercased, trimmed)

Return ONLY valid JSON, no markdown:
{{"canonical": "chosen name", "merged": true_or_false}}
"""


def get_existing_ingredient_names() -> list[str]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM ingredients ORDER BY name")
    names = [row["name"] for row in cur.fetchall()]
    conn.close()
    return names


def _parse_normalise_response(raw: str, name: str, existing: list[str]) -> str:
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result = json.loads(raw.strip())
        canonical = result.get("canonical", "").strip().lower()
        # Only accept if it's in the existing list (validated merge) or same as input (new item)
        if canonical and (canonical in existing or canonical == name):
            return canonical
    except (json.JSONDecodeError, AttributeError):
        pass
    return name


def normalise_ingredient(name: str, existing: list[str]) -> str:
    """Sync version — for use in synchronous DB write paths."""
    name = name.strip().lower()
    if not existing:
        return name
    # Fast path: exact match already in DB
    if name in existing:
        return name

    response = sync_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=64,
        messages=[{
            "role": "user",
            "content": NORMALISE_PROMPT.format(
                name=name,
                existing=json.dumps(existing[:300]),
            ),
        }],
    )
    return _parse_normalise_response(response.content[0].text, name, existing)


async def normalise_ingredient_async(name: str, existing: list[str]) -> str:
    """Async version — for use in async scan/upsert paths."""
    name = name.strip().lower()
    if not existing:
        return name
    if name in existing:
        return name

    response = await async_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=64,
        messages=[{
            "role": "user",
            "content": NORMALISE_PROMPT.format(
                name=name,
                existing=json.dumps(existing[:300]),
            ),
        }],
    )
    return _parse_normalise_response(response.content[0].text, name, existing)


async def normalise_batch_async(names: list[str], existing: list[str]) -> list[str]:
    """Normalise a list of ingredient names in parallel against existing DB names."""
    if not names:
        return names
    results = await asyncio.gather(
        *[normalise_ingredient_async(n, existing) for n in names]
    )
    # Deduplicate within the batch (two new items might normalise to the same canonical)
    seen = []
    for r in results:
        if r not in seen:
            seen.append(r)
    return seen


# ---------------------------------------------------------------------------
# One-time cleanup: normalise all existing DB ingredients against each other
# ---------------------------------------------------------------------------

async def _cleanup_pass(dry_run: bool = True):
    existing = get_existing_ingredient_names()
    print(f"[Normalise] {len(existing)} ingredients in DB")

    merges: list[tuple[str, str]] = []  # (old_name, canonical)

    for name in existing:
        # Build the "other" list (everything except this item)
        others = [n for n in existing if n != name]
        canonical = await normalise_ingredient_async(name, others)
        if canonical != name:
            merges.append((name, canonical))
            print(f"  MERGE: '{name}' → '{canonical}'")
        else:
            print(f"  keep:  '{name}'")

    print(f"\n[Normalise] {len(merges)} merge(s) found")

    if not merges:
        print("Nothing to do.")
        return

    if dry_run:
        print("\n[Normalise] DRY RUN — no changes written. Re-run without --dry-run to apply.")
        return

    conn = get_connection()
    cur = conn.cursor()
    for old_name, canonical_name in merges:
        # Get IDs
        cur.execute("SELECT id FROM ingredients WHERE name = ?", (old_name,))
        old_row = cur.fetchone()
        cur.execute("SELECT id FROM ingredients WHERE name = ?", (canonical_name,))
        canon_row = cur.fetchone()

        if not old_row or not canon_row:
            print(f"  [!] Skipping '{old_name}' → '{canonical_name}': one not found in DB")
            continue

        old_id = old_row["id"]
        canon_id = canon_row["id"]

        # Re-link recipe_ingredients to canonical
        cur.execute(
            "UPDATE OR IGNORE recipe_ingredients SET ingredient_id = ? WHERE ingredient_id = ?",
            (canon_id, old_id),
        )
        # Re-link aliases to canonical
        cur.execute(
            "UPDATE OR IGNORE ingredient_aliases SET ingredient_id = ? WHERE ingredient_id = ?",
            (canon_id, old_id),
        )
        # Insert old name as an alias for the canonical
        cur.execute(
            "INSERT OR IGNORE INTO ingredient_aliases (alias, ingredient_id) VALUES (?, ?)",
            (old_name, canon_id),
        )
        # Delete the old ingredient
        cur.execute("DELETE FROM ingredients WHERE id = ?", (old_id,))
        print(f"  [DB] Merged '{old_name}' → '{canonical_name}'")

    conn.commit()
    conn.close()
    print("\n[Normalise] Cleanup complete.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Normalise existing ingredients in kitchen.db")
    parser.add_argument("--dry-run", action="store_true", help="Preview merges without writing")
    args = parser.parse_args()
    asyncio.run(_cleanup_pass(dry_run=args.dry_run))
