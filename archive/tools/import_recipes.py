"""
Batch Recipe Importer
----------------------
Imports multiple recipes in parallel from URLs and/or a folder of .txt files.

Usage:
    python tools/import_recipes.py --urls https://... https://...
    python tools/import_recipes.py --folder recipes/
    python tools/import_recipes.py --urls https://... --folder recipes/
"""

import argparse
import asyncio
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from add_recipe import run as add_recipe_run


async def process_one(task: dict) -> dict:
    source = task["value"]
    kind = task["type"]
    try:
        if kind == "url":
            recipe_id = await asyncio.to_thread(add_recipe_run, url=source)
        else:
            recipe_id = await asyncio.to_thread(add_recipe_run, file=source)
        return {"source": source, "kind": kind, "recipe_id": recipe_id, "error": None}
    except Exception as e:
        return {"source": source, "kind": kind, "recipe_id": None, "error": str(e)}


async def run_batch(urls: list[str], folder: str | None):
    tasks = []

    for url in urls:
        tasks.append({"type": "url", "value": url})

    if folder:
        txt_files = glob.glob(os.path.join(folder, "*.txt"))
        for path in sorted(txt_files):
            tasks.append({"type": "file", "value": path})

    if not tasks:
        print("No sources provided. Use --urls or --folder.")
        return

    print(f"Importing {len(tasks)} recipe(s) in parallel...\n")

    results = await asyncio.gather(*[process_one(t) for t in tasks], return_exceptions=False)

    succeeded = [r for r in results if r["error"] is None]
    failed = [r for r in results if r["error"] is not None]

    print(f"\nImported {len(succeeded)}/{len(tasks)} recipes:")
    for r in succeeded:
        label = os.path.basename(r["source"]) if r["kind"] == "file" else r["source"]
        print(f"  +  (id={r['recipe_id']}) from {r['kind']}: {label}")
    for r in failed:
        label = os.path.basename(r["source"]) if r["kind"] == "file" else r["source"]
        print(f"  x  FAILED: {label}")
        print(f"       Error: {r['error']}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch Recipe Importer")
    parser.add_argument("--urls", nargs="+", metavar="URL", default=[], help="One or more recipe URLs")
    parser.add_argument("--folder", help="Folder containing .txt recipe files")
    args = parser.parse_args()
    asyncio.run(run_batch(args.urls, args.folder))
