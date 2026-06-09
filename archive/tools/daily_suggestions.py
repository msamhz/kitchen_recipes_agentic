"""
Daily Recipe Suggestion Agent
-------------------------------
Orchestrates: calendar check → recipe matching → filtered presentation → user selection → stock update.

Usage:
    python tools/daily_suggestions.py
    python tools/daily_suggestions.py --skip-calendar   # treat as non-WFH (strictest)
    python tools/daily_suggestions.py --force-wfh       # treat as WFH (show all options)
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from check_calendar import check_wfh
from match_recipes import match_recipes
from update_stock import mark_recipe_cooked
from db_init import get_connection


async def _gather_data(skip_calendar: bool, force_wfh: bool) -> tuple[bool, dict]:
    if force_wfh:
        print("[Calendar] Forced WFH=True")
        return True, match_recipes()
    if skip_calendar:
        print("[Calendar] Skipped — treating as non-WFH")
        return False, match_recipes()

    async def _safe_check_wfh():
        try:
            return await asyncio.to_thread(check_wfh)
        except Exception as e:
            print(f"[Calendar] Error: {e}")
            print("[Calendar] Falling back to non-WFH mode")
            return False

    wfh, results = await asyncio.gather(
        _safe_check_wfh(),
        asyncio.to_thread(match_recipes),
    )
    return wfh, results


def display_recipes(results: dict, wfh: bool) -> list[dict]:
    """
    Builds and prints the filtered recipe list.
    Returns the list of options shown to the user (for selection by number).
    """
    can_cook = results["can_cook"]
    can_shop = results["can_shop"]

    options = []

    print("\n" + "=" * 50)
    print(f"  WHAT TO COOK TODAY  (WFH={'Yes' if wfh else 'No'})")
    print("=" * 50)

    if can_cook:
        print("\n[All ingredients available]")
        for r in can_cook:
            idx = len(options) + 1
            options.append(r)
            opt_note = ""
            if r["missing_optional"]:
                opt_note = f"  (without: {', '.join(r['missing_optional'])})"
            print(f"  {idx}. {r['name']}{opt_note}")
    else:
        print("\n[All ingredients available]\n  (none — stock your kitchen or add recipes)")

    if wfh and can_shop:
        print("\n[Can cook if you buy these first]")
        for r in can_shop:
            idx = len(options) + 1
            options.append(r)
            missing = ", ".join(r["missing_required"])
            print(f"  {idx}. {r['name']}  [buy: {missing}]")

    if not options:
        print("\nNo recipes available. Try:")
        print("  - Taking a photo of your kitchen:  python tools/cv_to_ingredients.py --image <path>")
        print("  - Adding a recipe:                 python tools/add_recipe.py --text '...'")

    return options


def get_recipe_instructions(recipe_id: int) -> str:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT instructions FROM recipes WHERE id = ?", (recipe_id,))
    row = cur.fetchone()
    conn.close()
    return row["instructions"] if row else ""


def run(skip_calendar: bool = False, force_wfh: bool = False):
    # Steps 1+2: Calendar check and recipe matching run in parallel
    wfh, results = asyncio.run(_gather_data(skip_calendar, force_wfh))

    # Step 3: Display filtered list
    options = display_recipes(results, wfh=wfh)

    if not options:
        return

    # Step 4: User selection
    print("\n" + "-" * 50)
    choice = input("Select a recipe number to cook (or press Enter to skip): ").strip()

    if not choice:
        print("No selection made. Enjoy your day!")
        return

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(options):
            raise ValueError
    except ValueError:
        print("Invalid selection.")
        return

    selected = options[idx]
    print(f"\nSelected: {selected['name']}")

    # Step 5: Show instructions
    instructions = get_recipe_instructions(selected["id"])
    if instructions:
        print("\n--- Instructions ---")
        print(instructions)
        print("---")

    # Step 6: Confirm and update stock
    confirm = input("\nMark ingredients as used? (y/N): ").strip().lower()
    if confirm == "y":
        mark_recipe_cooked(selected["id"])
        print(f"[DB] Stock updated — ingredients for '{selected['name']}' marked as used.")
    else:
        print("Stock not updated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily Recipe Suggestions")
    parser.add_argument("--skip-calendar", action="store_true", help="Skip calendar check, assume non-WFH")
    parser.add_argument("--force-wfh", action="store_true", help="Force WFH mode regardless of calendar")
    args = parser.parse_args()
    run(skip_calendar=args.skip_calendar, force_wfh=args.force_wfh)
