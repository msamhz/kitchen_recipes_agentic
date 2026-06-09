"""
Shopping List Builder
----------------------
Reads can_shop recipes from the matcher and produces a deduplicated shopping list,
showing which recipes need each ingredient.

Usage:
    python tools/build_shopping_list.py
    python tools/build_shopping_list.py --recipes "Pad Thai" "Chicken Fried Rice"
    python tools/build_shopping_list.py --json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from match_recipes import match_recipes


def build_list(recipe_filter: list[str] | None = None) -> dict:
    results = match_recipes()
    can_shop = results["can_shop"]

    if recipe_filter:
        filter_lower = {r.lower() for r in recipe_filter}
        can_shop = [r for r in can_shop if r["name"].lower() in filter_lower]

    # ingredient_name -> list of recipe names that need it
    ingredient_map: dict[str, list[str]] = {}

    for recipe in can_shop:
        for ing in recipe["missing_required"]:
            key = ing.strip().lower()
            ingredient_map.setdefault(key, [])
            if recipe["name"] not in ingredient_map[key]:
                ingredient_map[key].append(recipe["name"])

    items = [
        {"ingredient": ing, "needed_for": recipes}
        for ing, recipes in sorted(ingredient_map.items())
    ]

    recipe_names = [r["name"] for r in can_shop]

    return {"items": items, "recipes": recipe_names}


def print_list(data: dict):
    items = data["items"]
    recipes = data["recipes"]

    if not items:
        print("Nothing to buy — either all recipes are cookable or no shop-first recipes exist.")
        return

    print(f"\n=== SHOPPING LIST ({len(items)} item{'s' if len(items) != 1 else ''}) ===")
    if recipes:
        print(f"\nTo cook: {', '.join(recipes)}\n")
    for item in items:
        needed = ", ".join(item["needed_for"])
        print(f"  [ ] {item['ingredient']:<25} -> {needed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Shopping List Builder")
    parser.add_argument(
        "--recipes", nargs="+", metavar="NAME",
        help="Limit to specific recipe names (must match exactly)"
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")
    args = parser.parse_args()

    data = build_list(recipe_filter=args.recipes)

    if args.as_json:
        print(json.dumps(data, indent=2))
    else:
        print_list(data)
