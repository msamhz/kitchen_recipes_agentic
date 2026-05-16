"""
Multi-image Kitchen Scanner
-----------------------------
Accepts multiple image paths, fires parallel Claude vision calls,
merges and deduplicates results, then does a single DB upsert.

Usage:
    python tools/scan_kitchen.py --images fridge.jpg pantry.jpg counter.jpg
    python tools/scan_kitchen.py --images fridge.jpg pantry.jpg --mode restock
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from cv_to_ingredients import identify_ingredients_async, resolve_uncertain_async, upsert_ingredients
from db_init import init_db

CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}


async def scan_kitchen(image_paths: list[str], mode: str = "update"):
    for path in image_paths:
        if not os.path.exists(path):
            print(f"ERROR: Image not found: {path}")
            sys.exit(1)

    init_db()
    print(f"[SCAN] Scanning {len(image_paths)} image(s) in parallel...")

    # Fire all image identifications in parallel
    all_results = await asyncio.gather(*[identify_ingredients_async(p) for p in image_paths])

    all_ingredients = []
    all_uncertain = []
    total_found = 0

    for path, result in zip(image_paths, all_results):
        ingredients = result.get("ingredients", [])
        uncertain = result.get("uncertain", [])
        total_found += len(ingredients)
        all_ingredients.extend(ingredients)
        all_uncertain.extend(uncertain)
        print(f"  [{path}] {len(ingredients)} ingredient(s), {len(uncertain)} uncertain")

    # Deduplicate — keep highest-confidence entry per ingredient name
    seen: dict[str, dict] = {}
    for item in all_ingredients:
        key = item["name"].strip().lower()
        if key not in seen or CONFIDENCE_RANK.get(item.get("confidence", "low"), 0) > CONFIDENCE_RANK.get(seen[key].get("confidence", "low"), 0):
            seen[key] = item

    deduped = list(seen.values())
    print(f"[SCAN] {total_found} total -> {len(deduped)} unique after dedup")

    confirmed_names = []
    to_resolve = []

    for item in deduped:
        if item["confidence"] in ("high", "medium"):
            confirmed_names.append(item["name"])
        else:
            to_resolve.append(item.get("notes", item["name"]))

    # Deduplicate uncertain items across all images
    seen_uncertain: set[str] = set()
    for desc in all_uncertain:
        key = desc.strip().lower()
        if key not in seen_uncertain:
            seen_uncertain.add(key)
            to_resolve.append(desc)

    # Resolve all uncertain items in one parallel gather
    if to_resolve:
        print(f"[SCAN] Resolving {len(to_resolve)} uncertain item(s) in parallel...")
        resolved = await asyncio.gather(*[resolve_uncertain_async(d) for d in to_resolve])
        for desc, name in zip(to_resolve, resolved):
            if name:
                confirmed_names.append(name)
                print(f"      -> '{desc}' resolved to: {name}")
            else:
                print(f"      -> '{desc}' skipped")

    if confirmed_names:
        upsert_ingredients(confirmed_names, mode=mode)
        print(f"\n[SCAN] Summary: {len(image_paths)} image(s), {len(confirmed_names)} ingredient(s) saved (mode={mode})")
    else:
        print("\n[DB] No ingredients to save.")

    return confirmed_names


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-image kitchen scanner")
    parser.add_argument("--images", nargs="+", required=True, help="Paths to kitchen photos")
    parser.add_argument(
        "--mode",
        choices=["update", "restock"],
        default="update",
        help="update: add detected items; restock: replace entire stock with what's in photos",
    )
    args = parser.parse_args()
    asyncio.run(scan_kitchen(args.images, args.mode))
