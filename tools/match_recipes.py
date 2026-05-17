"""
Recipe Matcher Tool — fully deterministic, no LLM calls.
----------------------------------------------------------
Queries kitchen.db and returns:
  - can_cook:    recipes where ALL required ingredients are in stock
  - missing_one: recipes where only optional ingredients are missing
                 (required all present)
  - can_shop:    recipes with 1+ required ingredients out of stock,
                 along with the specific missing ingredients

Usage:
    python tools/match_recipes.py
    python tools/match_recipes.py --json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from db_init import get_connection


def match_recipes() -> dict:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, name FROM recipes ORDER BY name")
    recipes = cur.fetchall()

    can_cook = []
    can_shop = []

    for recipe in recipes:
        rid = recipe["id"]
        rname = recipe["name"]

        cur.execute(
            """
            SELECT
                i.name,
                ri.is_optional,
                CASE
                    WHEN i.in_stock = 1 THEN 1
                    WHEN EXISTS (
                        SELECT 1 FROM ingredient_aliases ia
                        JOIN ingredients i2 ON i2.id = ia.ingredient_id
                        WHERE ia.alias = i.name COLLATE NOCASE AND i2.in_stock = 1
                    ) THEN 1
                    ELSE 0
                END AS in_stock
            FROM recipe_ingredients ri
            JOIN ingredients i ON i.id = ri.ingredient_id
            WHERE ri.recipe_id = ?
            """,
            (rid,),
        )
        ingredients = cur.fetchall()

        if not ingredients:
            continue

        missing_required = [
            i["name"] for i in ingredients if not i["is_optional"] and not i["in_stock"]
        ]
        missing_optional = [
            i["name"] for i in ingredients if i["is_optional"] and not i["in_stock"]
        ]
        have = [
            i["name"] for i in ingredients if i["in_stock"]
        ]

        if not missing_required:
            can_cook.append({
                "id": rid,
                "name": rname,
                "have": have,
                "missing_optional": missing_optional,
            })
        else:
            can_shop.append({
                "id": rid,
                "name": rname,
                "have": have,
                "missing_required": missing_required,
                "missing_optional": missing_optional,
            })

    conn.close()

    return {
        "can_cook": can_cook,
        "can_shop": can_shop,
    }


def print_results(results: dict, wfh: bool = True):
    can_cook = results["can_cook"]
    can_shop = results["can_shop"]

    print("\n=== RECIPES YOU CAN COOK NOW ===")
    if can_cook:
        for i, r in enumerate(can_cook, 1):
            optional_note = ""
            if r["missing_optional"]:
                optional_note = f"  (missing optional: {', '.join(r['missing_optional'])})"
            print(f"  {i}. {r['name']}{optional_note}")
    else:
        print("  None — check your stock or add more recipes.")

    if wfh:
        print("\n=== RECIPES YOU CAN COOK IF YOU SHOP (WFH day) ===")
        if can_shop:
            for i, r in enumerate(can_shop, 1):
                missing = ", ".join(r["missing_required"])
                print(f"  {i}. {r['name']}  [need to buy: {missing}]")
        else:
            print("  None.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recipe Matcher")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--wfh", action="store_true", default=True, help="Show shop-first recipes (WFH mode)")
    parser.add_argument("--no-wfh", dest="wfh", action="store_false")
    args = parser.parse_args()

    results = match_recipes()

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_results(results, wfh=args.wfh)
