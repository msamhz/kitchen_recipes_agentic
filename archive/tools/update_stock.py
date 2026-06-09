"""
Stock Update Tool
------------------
Marks required ingredients of a cooked recipe as out of stock (in_stock=0).
Optional ingredients are left unchanged.

Also supports manual stock edits.

Usage:
    python tools/update_stock.py --recipe-id 3
    python tools/update_stock.py --recipe-name "Spaghetti Bolognese"
    python tools/update_stock.py --out "chicken breast" "garlic"
    python tools/update_stock.py --in "olive oil" "tomatoes"
    python tools/update_stock.py --list
"""

import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))
from db_init import get_connection


def mark_recipe_cooked(recipe_id: int):
    """Mark all required ingredients of a recipe as out of stock."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE ingredients
        SET in_stock = 0, last_updated = datetime('now')
        WHERE id IN (
            SELECT ingredient_id FROM recipe_ingredients
            WHERE recipe_id = ? AND is_optional = 0
        )
        """,
        (recipe_id,),
    )
    affected = cur.rowcount
    conn.commit()
    conn.close()
    print(f"[Stock] Marked {affected} required ingredients as used (recipe_id={recipe_id})")
    return affected


def get_required_ingredients(recipe_id: int) -> list[dict]:
    """
    Returns required ingredients for a recipe.
    Each entry has:
      display_name  — ingredient name as written in the recipe
      stocked_name  — actual stock item name (may differ via alias), or None if not in stock
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            i.name AS display_name,
            CASE
                WHEN i.in_stock = 1 THEN i.name
                ELSE (
                    SELECT i2.name FROM ingredient_aliases ia
                    JOIN ingredients i2 ON i2.id = ia.ingredient_id
                    WHERE ia.alias = i.name COLLATE NOCASE AND i2.in_stock = 1
                    LIMIT 1
                )
            END AS stocked_name
        FROM recipe_ingredients ri
        JOIN ingredients i ON i.id = ri.ingredient_id
        WHERE ri.recipe_id = ? AND ri.is_optional = 0
        ORDER BY i.name
        """,
        (recipe_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [{"display_name": r["display_name"], "stocked_name": r["stocked_name"]} for r in rows]


def mark_ingredients(names: list[str], in_stock: bool):
    conn = get_connection()
    cur = conn.cursor()
    for name in names:
        cur.execute(
            "UPDATE ingredients SET in_stock = ?, last_updated = datetime('now') WHERE name = ?",
            (1 if in_stock else 0, name.strip().lower()),
        )
        if cur.rowcount == 0:
            print(f"  [!] Ingredient not found in DB: '{name}'")
        else:
            status = "in stock" if in_stock else "out of stock"
            print(f"  [Stock] '{name}' -> {status}")
    conn.commit()
    conn.close()


def list_stock():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, in_stock, last_updated FROM ingredients ORDER BY name")
    rows = cur.fetchall()
    conn.close()

    in_stock = [r for r in rows if r["in_stock"]]
    out_of_stock = [r for r in rows if not r["in_stock"]]

    print(f"\n=== KITCHEN STOCK ({len(rows)} total) ===")
    print(f"\nIN STOCK ({len(in_stock)}):")
    for r in in_stock:
        print(f"  + {r['name']}")

    print(f"\nOUT OF STOCK ({len(out_of_stock)}):")
    for r in out_of_stock:
        print(f"  - {r['name']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock Update Tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--recipe-id", type=int, help="Mark all required ingredients of a recipe as used")
    group.add_argument("--recipe-name", help="Same as --recipe-id but by name")
    group.add_argument("--out", nargs="+", metavar="INGREDIENT", help="Mark ingredients as out of stock")
    group.add_argument("--in", nargs="+", metavar="INGREDIENT", dest="in_stock", help="Mark ingredients as in stock")
    group.add_argument("--list", action="store_true", help="List current stock")
    args = parser.parse_args()

    if args.list:
        list_stock()

    elif args.recipe_id:
        mark_recipe_cooked(args.recipe_id)

    elif args.recipe_name:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM recipes WHERE name = ?", (args.recipe_name,))
        row = cur.fetchone()
        conn.close()
        if not row:
            print(f"ERROR: Recipe not found: '{args.recipe_name}'")
            sys.exit(1)
        mark_recipe_cooked(row["id"])

    elif args.out:
        mark_ingredients(args.out, in_stock=False)

    elif args.in_stock:
        mark_ingredients(args.in_stock, in_stock=True)
