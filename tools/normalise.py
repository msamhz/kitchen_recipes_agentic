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

_CLEANUP_PROMPT = """You are deduplicating a kitchen ingredient database used in Singapore.

Here is the full list of ingredient names currently in the database:
{ingredients}

Your task:
1. Find groups of entries that refer to the SAME physical ingredient.
   - Brand + generic: "tiparos fish sauce" and "fish sauce" are the same — use the generic
   - Plurals: "egg" and "eggs" — keep the plural
   - Multilingual: "mahsuri kicap lemak manis" and "sweet soy sauce (kicap lemak manis)" — keep the cleaner English/common form
   - Minor variants: "cooking oil" and "oil" — keep the shorter common form
   - Brand duplicates: two brand names for the same product — keep the more well-known or shorter one
2. For each group, choose ONE canonical name (prefer: shorter, generic, English, common name)
3. Only merge when HIGHLY confident — different spices are NOT the same even if related
   - "chilli" and "chilli padi" are DIFFERENT (chilli padi = bird's eye chili, much hotter)
   - "lemon" and "lime" are DIFFERENT fruits
   - "tomatoes" and "tomato sauce" are DIFFERENT
   - "prunes" and "dates" are DIFFERENT
   - "beef" and "beef short plate slices" — these are the same cut, merge to "beef"
4. Items that are genuinely distinct should NOT be merged

Return ONLY valid JSON:
{{
  "groups": [
    {{"canonical": "chosen name", "duplicates": ["name to remove 1", "name to remove 2"]}},
    ...
  ]
}}

Only include groups where there are actual duplicates. Do not list groups with a single item.
"""


async def _find_merge_groups(names: list[str]) -> list[dict]:
    """Send the full ingredient list to Sonnet and get back merge groups."""
    response = await async_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": _CLEANUP_PROMPT.format(ingredients=json.dumps(names)),
        }],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    # Extract JSON block regardless of surrounding text
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    else:
        # Find the first { in case there's preamble text
        idx = raw.find("{")
        if idx != -1:
            raw = raw[idx:]
    try:
        data = json.loads(raw.strip())
        return data.get("groups", [])
    except (json.JSONDecodeError, AttributeError):
        return []


async def _cleanup_pass(dry_run: bool = True):
    existing = get_existing_ingredient_names()
    print(f"[Normalise] {len(existing)} ingredients in DB — sending to Claude for grouping...")

    groups = await _find_merge_groups(existing)

    if not groups:
        print("No duplicates found.")
        return

    # Validate: canonical and all duplicates must actually be in the DB
    valid_set = set(n.lower() for n in existing)
    merges: list[tuple[str, str]] = []  # (duplicate_to_remove, canonical)

    for group in groups:
        canonical = group.get("canonical", "").strip().lower()
        duplicates = [d.strip().lower() for d in group.get("duplicates", [])]

        if not canonical or canonical not in valid_set:
            print(f"  [!] Skip group — canonical '{canonical}' not in DB")
            continue

        print(f"\n  CANONICAL: '{canonical}'")
        for dup in duplicates:
            if dup not in valid_set:
                print(f"    [!] Skip '{dup}' — not in DB")
                continue
            if dup == canonical:
                continue
            print(f"    MERGE: '{dup}' -> '{canonical}'")
            merges.append((dup, canonical))

    print(f"\n[Normalise] {len(merges)} merge(s) found across {len(groups)} group(s)")

    if not merges:
        print("Nothing to do.")
        return

    if dry_run:
        print("\n[Normalise] DRY RUN — no changes written. Re-run without --dry-run to apply.")
        return

    conn = get_connection()
    cur = conn.cursor()
    for old_name, canonical_name in merges:
        cur.execute("SELECT id FROM ingredients WHERE name = ?", (old_name,))
        old_row = cur.fetchone()
        cur.execute("SELECT id FROM ingredients WHERE name = ?", (canonical_name,))
        canon_row = cur.fetchone()

        if not old_row or not canon_row:
            print(f"  [!] Skipping '{old_name}' -> '{canonical_name}': one not found")
            continue

        old_id = old_row["id"]
        canon_id = canon_row["id"]

        cur.execute(
            "UPDATE OR IGNORE recipe_ingredients SET ingredient_id = ? WHERE ingredient_id = ?",
            (canon_id, old_id),
        )
        cur.execute(
            "UPDATE OR IGNORE ingredient_aliases SET ingredient_id = ? WHERE ingredient_id = ?",
            (canon_id, old_id),
        )
        cur.execute(
            "INSERT OR IGNORE INTO ingredient_aliases (alias, ingredient_id) VALUES (?, ?)",
            (old_name, canon_id),
        )
        cur.execute("DELETE FROM ingredients WHERE id = ?", (old_id,))
        print(f"  [DB] Merged '{old_name}' -> '{canonical_name}'")

    conn.commit()
    conn.close()
    print("\n[Normalise] Cleanup complete.")


if __name__ == "__main__":
    import argparse
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Normalise existing ingredients in kitchen.db")
    parser.add_argument("--dry-run", action="store_true", help="Preview merges without writing")
    args = parser.parse_args()
    asyncio.run(_cleanup_pass(dry_run=args.dry_run))
