"""
Ingredient Normaliser
----------------------
Resolves a new ingredient name to a canonical form before any DB write.

Strategy (Block 3 — vector-first):
  1. Exact match         → return immediately, zero cost
  2. Vector similarity >= 0.85 (confident)  → return match, zero LLM cost
  3. Vector similarity 0.75-0.85 (grey zone) → one small LLM call with top-3 neighbours only
  4. Vector similarity < 0.75 (new)          → return as-is, zero LLM cost

LLM is only ever called for the grey zone, with a prompt of ~100 tokens
instead of the full ingredient list.

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
from ingredient_index import get_index, reset_index

# ---------------------------------------------------------------------------
# Grey zone LLM confirmation — tiny prompt, top-3 neighbours only
# ---------------------------------------------------------------------------

_GREY_PROMPT = """Kitchen ingredient deduplication. Singapore context.

New ingredient: "{name}"

Closest matches already in the database:
{neighbours}

Is the new ingredient the SAME physical ingredient as one of the above?
- Consider: brand variants, plurals, multilingual names (Malay/Chinese/English)
- Only say yes if HIGHLY confident — similar-sounding but different things should stay separate

Return ONLY valid JSON:
{{"match_index": 1, "canonical": "exact db name"}}
or if no match:
{{"match_index": null, "canonical": null}}
"""


def _format_neighbours(neighbours: list[tuple[str, float]]) -> str:
    return "\n".join(
        f"{i+1}. \"{name}\" (similarity: {score:.2f})"
        for i, (name, score) in enumerate(neighbours[:3])
    )


def _parse_grey_response(raw: str, neighbours: list[tuple[str, float]]) -> str | None:
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result = json.loads(raw.strip())
        idx = result.get("match_index")
        canonical = result.get("canonical", "")
        if idx is not None and canonical:
            # Validate the returned name is actually a top-3 neighbour
            neighbour_names = [n for n, _ in neighbours[:3]]
            if canonical.strip().lower() in [n.lower() for n in neighbour_names]:
                return canonical.strip().lower()
    except (json.JSONDecodeError, AttributeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Core normalise functions
# ---------------------------------------------------------------------------

def normalise_ingredient(name: str, _existing: list[str] | None = None) -> str:
    """
    Sync normalisation using vector index + grey zone LLM fallback.
    `_existing` param kept for backward compat but ignored — index is used instead.
    """
    name = name.strip().lower()
    index = get_index()
    result = index.find(name)

    if result.zone == "confident":
        return result.match

    if result.zone == "grey":
        response = sync_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            messages=[{
                "role": "user",
                "content": _GREY_PROMPT.format(
                    name=name,
                    neighbours=_format_neighbours(result.neighbours),
                ),
            }],
        )
        confirmed = _parse_grey_response(response.content[0].text, result.neighbours)
        if confirmed:
            return confirmed

    # zone == "new" or grey zone LLM declined merge
    return name


async def normalise_ingredient_async(name: str, _existing: list[str] | None = None) -> str:
    """Async version of normalise_ingredient."""
    name = name.strip().lower()
    index = get_index()
    result = index.find(name)

    if result.zone == "confident":
        return result.match

    if result.zone == "grey":
        response = await async_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            messages=[{
                "role": "user",
                "content": _GREY_PROMPT.format(
                    name=name,
                    neighbours=_format_neighbours(result.neighbours),
                ),
            }],
        )
        confirmed = _parse_grey_response(response.content[0].text, result.neighbours)
        if confirmed:
            return confirmed

    return name


async def normalise_batch_async(
    names: list[str],
    _existing: list[str] | None = None,
) -> list[str]:
    """
    Normalise a batch of names.
    - Confident + new zones: resolved instantly via vectors, no LLM
    - Grey zone items: one parallel gather of small LLM calls (top-3 neighbours only)
    Returns deduplicated list.
    """
    if not names:
        return names

    index = get_index()
    results = [index.find(n.strip().lower()) for n in names]

    confident_or_new = []
    grey_indices = []

    for i, r in enumerate(results):
        if r.zone == "confident":
            confident_or_new.append((i, r.match))
        elif r.zone == "new":
            confident_or_new.append((i, r.name))
        else:
            grey_indices.append(i)

    # Resolve grey zone items in parallel — one small call each
    grey_resolved: list[str | None] = []
    if grey_indices:
        grey_tasks = [
            async_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=64,
                messages=[{
                    "role": "user",
                    "content": _GREY_PROMPT.format(
                        name=results[i].name,
                        neighbours=_format_neighbours(results[i].neighbours),
                    ),
                }],
            )
            for i in grey_indices
        ]
        responses = await asyncio.gather(*grey_tasks)
        for resp, i in zip(responses, grey_indices):
            confirmed = _parse_grey_response(resp.content[0].text, results[i].neighbours)
            grey_resolved.append(confirmed if confirmed else results[i].name)

    # Merge all results back in original order
    final: list[str] = [""] * len(names)
    for i, val in confident_or_new:
        final[i] = val
    for list_pos, orig_idx in enumerate(grey_indices):
        final[orig_idx] = grey_resolved[list_pos]

    # Deduplicate while preserving order
    seen = []
    for name in final:
        if name and name not in seen:
            seen.append(name)
    return seen


# ---------------------------------------------------------------------------
# DB helper (used by add_recipe and cleanup)
# ---------------------------------------------------------------------------

def get_existing_ingredient_names() -> list[str]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM ingredients ORDER BY name")
    names = [row["name"] for row in cur.fetchall()]
    conn.close()
    return names


# ---------------------------------------------------------------------------
# One-time cleanup: holistic LLM grouping of full ingredient list
# ---------------------------------------------------------------------------

_CLEANUP_PROMPT = """You are deduplicating a kitchen ingredient database used in Singapore.

Here is the full list of ingredient names currently in the database:
{ingredients}

Your task:
1. Find groups of entries that refer to the SAME physical ingredient.
   - Brand + generic: "tiparos fish sauce" and "fish sauce" — use the generic
   - Plurals: "egg" and "eggs" — keep the plural
   - Multilingual: "mahsuri kicap lemak manis" and "sweet soy sauce (kicap lemak manis)" — keep cleaner form
   - Minor variants: "cooking oil" and "oil" — keep shorter common form
2. For each group, choose ONE canonical name (prefer: shorter, generic, English, common name)
3. Only merge when HIGHLY confident — different spices are NOT the same even if related
   - "chilli" and "chilli padi" are DIFFERENT (chilli padi = bird's eye chili, much hotter)
   - "lemon" and "lime" are DIFFERENT fruits
   - "tomatoes" and "tomato sauce" are DIFFERENT
4. Items that are genuinely distinct should NOT be merged

Return ONLY valid JSON:
{{
  "groups": [
    {{"canonical": "chosen name", "duplicates": ["name to remove 1", "name to remove 2"]}},
    ...
  ]
}}

Only include groups where there are actual duplicates.
"""


async def _find_merge_groups(names: list[str]) -> list[dict]:
    response = await async_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": _CLEANUP_PROMPT.format(ingredients=json.dumps(names)),
        }],
    )
    raw = response.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    else:
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

    valid_set = set(n.lower() for n in existing)
    merges: list[tuple[str, str]] = []

    for group in groups:
        canonical = group.get("canonical", "").strip().lower()
        duplicates = [d.strip().lower() for d in group.get("duplicates", [])]
        if not canonical or canonical not in valid_set:
            print(f"  [!] Skip group — canonical '{canonical}' not in DB")
            continue
        print(f"\n  CANONICAL: '{canonical}'")
        for dup in duplicates:
            if dup not in valid_set or dup == canonical:
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
        old_id, canon_id = old_row["id"], canon_row["id"]
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
    # Reload index after bulk merges
    reset_index()
    print("\n[Normalise] Cleanup complete. Index reset.")


if __name__ == "__main__":
    import argparse
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Normalise existing ingredients in kitchen.db")
    parser.add_argument("--dry-run", action="store_true", help="Preview merges without writing")
    args = parser.parse_args()
    asyncio.run(_cleanup_pass(dry_run=args.dry_run))
