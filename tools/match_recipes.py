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
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from db_init import get_connection

# Urgency points per ingredient:
# expired → 1000, ≤3 days → 50, ≤7 days → 20, ≤14 days → 5
# Perishable (fridge/freezer) with no expiry date → +2 (tiebreak vs non-perishable)
_URGENCY_EXPIRED  = 1000
_URGENCY_3_DAYS   = 50
_URGENCY_7_DAYS   = 20
_URGENCY_14_DAYS  = 5
_URGENCY_PERISHABLE_NO_DATE = 2


def _ingredient_urgency(expiry_date_str: str | None, storage: str | None) -> int:
    """Return urgency points for a single in-stock ingredient."""
    if expiry_date_str:
        try:
            days_left = (date.fromisoformat(expiry_date_str) - date.today()).days
            if days_left < 0:
                return _URGENCY_EXPIRED
            if days_left <= 3:
                return _URGENCY_3_DAYS
            if days_left <= 7:
                return _URGENCY_7_DAYS
            if days_left <= 14:
                return _URGENCY_14_DAYS
        except ValueError:
            pass
    # No expiry date — perishable items (fridge/freezer) still get a small bump
    if storage in ("fridge", "freezer"):
        return _URGENCY_PERISHABLE_NO_DATE
    return 0


def match_recipes() -> dict:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, name, difficulty, prep_time FROM recipes ORDER BY name")
    recipes = cur.fetchall()

    can_cook = []
    can_shop = []
    today_str = date.today().isoformat()

    for recipe in recipes:
        rid = recipe["id"]
        rname = recipe["name"]

        cur.execute(
            """
            SELECT
                i.name,
                i.expiry_date,
                i.storage_location,
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
        have = [i["name"] for i in ingredients if i["in_stock"]]

        # Compute urgency from in-stock required ingredients only
        urgency_score = 0
        expiring_ingredients = []
        for ing in ingredients:
            if not ing["in_stock"] or ing["is_optional"]:
                continue
            pts = _ingredient_urgency(ing["expiry_date"], ing["storage_location"])
            urgency_score += pts
            if pts > 0 and ing["expiry_date"]:
                try:
                    days_left = (date.fromisoformat(ing["expiry_date"]) - date.today()).days
                    expiring_ingredients.append({
                        "name": ing["name"],
                        "expiry_date": ing["expiry_date"],
                        "days_left": days_left,
                    })
                except ValueError:
                    pass

        # Sort expiring list: most urgent first
        expiring_ingredients.sort(key=lambda x: x["days_left"])

        meta = {
            "difficulty": recipe["difficulty"],
            "prep_time": recipe["prep_time"],
            "urgency_score": urgency_score,
            "expiring_ingredients": expiring_ingredients,
        }

        if not missing_required:
            can_cook.append({
                "id": rid,
                "name": rname,
                "have": have,
                "missing_optional": missing_optional,
                **meta,
            })
        else:
            can_shop.append({
                "id": rid,
                "name": rname,
                "have": have,
                "missing_required": missing_required,
                "missing_optional": missing_optional,
                **meta,
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
