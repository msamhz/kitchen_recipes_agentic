from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date
from api.db import get_connection

router = APIRouter()

_URGENCY_EXPIRED          = 1000
_URGENCY_3_DAYS           = 50
_URGENCY_7_DAYS           = 20
_URGENCY_14_DAYS          = 5
_URGENCY_PERISHABLE_NO_DATE = 2


def _ingredient_urgency(expiry_date_str: str | None, storage: str | None) -> int:
    if expiry_date_str:
        try:
            days_left = (date.fromisoformat(expiry_date_str) - date.today()).days
            if days_left < 0:   return _URGENCY_EXPIRED
            if days_left <= 3:  return _URGENCY_3_DAYS
            if days_left <= 7:  return _URGENCY_7_DAYS
            if days_left <= 14: return _URGENCY_14_DAYS
        except ValueError:
            pass
    if storage in ("fridge", "freezer"):
        return _URGENCY_PERISHABLE_NO_DATE
    return 0


@router.get("")
def get_recipes():
    """Return can_cook and can_shop recipe lists, urgency-ranked."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, name, difficulty, prep_time FROM recipes ORDER BY name")
    recipes = cur.fetchall()

    can_cook, can_shop = [], []
    today = date.today().isoformat()

    for recipe in recipes:
        rid = recipe["id"]

        cur.execute("""
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
                        WHERE ia.alias = i.name AND i2.in_stock = 1
                    ) THEN 1
                    ELSE 0
                END AS in_stock
            FROM recipe_ingredients ri
            JOIN ingredients i ON i.id = ri.ingredient_id
            WHERE ri.recipe_id = %s
        """, (rid,))
        ingredients = cur.fetchall()

        if not ingredients:
            continue

        missing_required = [i["name"] for i in ingredients if not i["is_optional"] and not i["in_stock"]]
        missing_optional = [i["name"] for i in ingredients if i["is_optional"] and not i["in_stock"]]
        have = [i["name"] for i in ingredients if i["in_stock"]]

        urgency_score = 0
        expiring = []
        for ing in ingredients:
            if not ing["in_stock"] or ing["is_optional"]:
                continue
            pts = _ingredient_urgency(ing["expiry_date"], ing["storage_location"])
            urgency_score += pts
            if pts > 0 and ing["expiry_date"]:
                try:
                    days_left = (date.fromisoformat(ing["expiry_date"]) - date.today()).days
                    expiring.append({"name": ing["name"], "expiry_date": ing["expiry_date"], "days_left": days_left})
                except ValueError:
                    pass

        expiring.sort(key=lambda x: x["days_left"])

        entry = {
            "id": rid,
            "name": recipe["name"],
            "difficulty": recipe["difficulty"],
            "prep_time": recipe["prep_time"],
            "have": have,
            "missing_optional": missing_optional,
            "urgency_score": urgency_score,
            "expiring_ingredients": expiring,
        }

        if not missing_required:
            can_cook.append(entry)
        else:
            can_shop.append({**entry, "missing_required": missing_required})

    conn.close()

    can_cook.sort(key=lambda r: -r["urgency_score"])
    can_shop.sort(key=lambda r: -r["urgency_score"])

    return {"can_cook": can_cook, "can_shop": can_shop}


class RecipeIngredient(BaseModel):
    name: str
    is_optional: bool = False


class RecipeCreate(BaseModel):
    name: str
    instructions: str
    difficulty: Optional[str] = None
    prep_time: Optional[str] = None
    source: Optional[str] = None
    ingredients: list[RecipeIngredient]


@router.post("")
def create_recipe(body: RecipeCreate):
    """Add a new recipe with its ingredients."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO recipes (name, instructions, difficulty, prep_time, source)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (name) DO UPDATE SET
            instructions = EXCLUDED.instructions,
            difficulty   = EXCLUDED.difficulty,
            prep_time    = EXCLUDED.prep_time
        RETURNING id
    """, (body.name, body.instructions, body.difficulty, body.prep_time, body.source))
    recipe_id = cur.fetchone()["id"]

    cur.execute("DELETE FROM recipe_ingredients WHERE recipe_id = %s", (recipe_id,))

    for ing in body.ingredients:
        cur.execute("""
            INSERT INTO ingredients (name, in_stock) VALUES (%s, 0)
            ON CONFLICT (name) DO NOTHING
        """, (ing.name,))
        cur.execute("SELECT id FROM ingredients WHERE name = %s", (ing.name,))
        ing_id = cur.fetchone()["id"]
        cur.execute("""
            INSERT INTO recipe_ingredients (recipe_id, ingredient_id, is_optional)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (recipe_id, ing_id, 1 if ing.is_optional else 0))

    conn.commit()
    conn.close()
    return {"created": recipe_id, "name": body.name}


@router.delete("/{recipe_id}")
def delete_recipe(recipe_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM recipes WHERE id = %s", (recipe_id,))
    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Recipe not found")
    conn.commit()
    conn.close()
    return {"deleted": recipe_id}
