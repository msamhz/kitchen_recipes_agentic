import concurrent.futures
import json
import os

from fastapi import APIRouter, HTTPException
from datetime import date

from kitchen_core.clients import sync_client
from kitchen_core.db import get_connection
from kitchen_core.ingredient_index import get_index
from kitchen_core.normalise import normalise_ingredient
from kitchen_core.schemas import RecipeCreate, ParseUrlRequest

router = APIRouter()

_URGENCY_EXPIRED            = 1000
_URGENCY_3_DAYS             = 50
_URGENCY_7_DAYS             = 20
_URGENCY_14_DAYS            = 5
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


@router.post("")
def create_recipe(body: RecipeCreate):
    """Add a new recipe with its ingredients.
    Ingredient names are normalised before saving to merge duplicates."""
    conn = get_connection()
    cur = conn.cursor()
    index = get_index()

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

    seen_ings: set[str] = set()
    for ing in body.ingredients:
        canonical = normalise_ingredient(ing.name.strip().lower())
        if canonical in seen_ings:
            continue
        seen_ings.add(canonical)

        cur.execute("""
            INSERT INTO ingredients (name, in_stock) VALUES (%s, 0)
            ON CONFLICT (name) DO NOTHING
        """, (canonical,))
        cur.execute("SELECT id FROM ingredients WHERE name = %s", (canonical,))
        ing_id = cur.fetchone()["id"]
        cur.execute("""
            INSERT INTO recipe_ingredients (recipe_id, ingredient_id, is_optional)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (recipe_id, ing_id, 1 if ing.is_optional else 0))

        if canonical not in index.names:
            try:
                index.embed_and_save(canonical)
            except Exception:
                pass

    conn.commit()
    conn.close()
    return {"created": recipe_id, "name": body.name}


@router.get("/shopping-list")
def get_shopping_list():
    """Return missing required ingredients with raw pairs for client-side filtering."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT i.name AS ingredient, r.id AS recipe_id, r.name AS recipe_name
        FROM recipes r
        JOIN recipe_ingredients ri ON ri.recipe_id = r.id
        JOIN ingredients i ON i.id = ri.ingredient_id
        WHERE ri.is_optional = 0
          AND i.in_stock = 0
          AND NOT EXISTS (
              SELECT 1 FROM ingredient_aliases ia
              JOIN ingredients i2 ON i2.id = ia.ingredient_id
              WHERE ia.alias = i.name AND i2.in_stock = 1
          )
        ORDER BY i.name, r.name
    """)
    pairs = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT id, name FROM recipes ORDER BY name")
    recipes = [dict(r) for r in cur.fetchall()]

    conn.close()
    return {"pairs": pairs, "recipes": recipes}


_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}

_PARSE_PROMPT = """You are a recipe parser. Extract the recipe from the text below.

Return ONLY valid JSON in this exact format:
{{
  "name": "Recipe Name",
  "instructions": "Full cooking instructions as a single string",
  "source": "URL or source if known, else null",
  "ingredients": [
    {{"name": "ingredient name (lowercase, common name)", "is_optional": false}},
    ...
  ]
}}

Rules:
- ingredient names should be the base ingredient only (e.g. "garlic" not "3 cloves of garlic")
- is_optional is true only if the recipe explicitly marks it optional or "to taste" garnishes
- instructions should be complete but concise

Recipe text:
---
{text}
---
"""

_RATE_PROMPT = """You are rating a recipe for a kitchen assistant app.

Recipe name: {name}
Instructions:
{instructions}

Determine:
1. difficulty — easy | medium | hard
2. prep_time — under_10 | 10_to_20 | over_20

Return ONLY valid JSON, no markdown:
{{"difficulty": "easy|medium|hard", "prep_time": "under_10|10_to_20|over_20"}}
"""


def _is_youtube(url: str) -> bool:
    from urllib.parse import urlparse
    return urlparse(url).hostname in _YOUTUBE_HOSTS


def _fetch_web(url: str) -> str:
    import requests
    from bs4 import BeautifulSoup
    in_lambda = bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
    headers = {"User-Agent": "Mozilla/5.0 (compatible; KitchenBot/1.0)"}
    resp = requests.get(url, headers=headers, timeout=20, verify=in_lambda)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)[:8000]


def _fetch_youtube(url: str) -> str:
    try:
        import yt_dlp
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "nocheckcertificate": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        title = info.get("title", "")
        desc = info.get("description", "")
        if desc:
            return f"Video title: {title}\n\n{desc}"[:8000]
    except Exception:
        pass

    import requests as _req
    import re
    import html as _html
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = _req.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    page = resp.text

    title_m = re.search(r'<title>([^<]+)</title>', page)
    title = _html.unescape(title_m.group(1).replace(" - YouTube", "").strip()) if title_m else ""

    desc_m = re.search(r'"shortDescription":"((?:[^"\\]|\\.)*)"', page)
    if desc_m:
        raw = desc_m.group(1)
        desc = raw.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
    else:
        og_m = re.search(r'<meta name="description" content="([^"]*)"', page)
        desc = _html.unescape(og_m.group(1)) if og_m else ""

    if not desc:
        raise ValueError("Could not extract description from YouTube page")
    return f"Video title: {title}\n\n{desc}"[:8000]


@router.post("/parse-url")
def parse_recipe_url(body: ParseUrlRequest):
    """Fetch a recipe page or YouTube video and return parsed recipe data (does not save)."""
    try:
        text = _fetch_youtube(body.url) if _is_youtube(body.url) else _fetch_web(body.url)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not fetch URL: {e}")

    def _strip_md(raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return raw.strip()

    def do_parse():
        resp = sync_client.messages.create(
            model="claude-sonnet-4-6", max_tokens=2048,
            messages=[{"role": "user", "content": _PARSE_PROMPT.format(text=text)}],
        )
        return json.loads(_strip_md(resp.content[0].text))

    def do_rate():
        resp = sync_client.messages.create(
            model="claude-sonnet-4-6", max_tokens=128,
            messages=[{"role": "user", "content": _RATE_PROMPT.format(name="", instructions=text[:4000])}],
        )
        try:
            r = json.loads(_strip_md(resp.content[0].text))
            return {
                "difficulty": r.get("difficulty") if r.get("difficulty") in {"easy", "medium", "hard"} else None,
                "prep_time": r.get("prep_time") if r.get("prep_time") in {"under_10", "10_to_20", "over_20"} else None,
            }
        except Exception:
            return {"difficulty": None, "prep_time": None}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        parse_f = pool.submit(do_parse)
        rate_f  = pool.submit(do_rate)
        recipe  = parse_f.result()
        rating  = rate_f.result()

    recipe["difficulty"] = rating.get("difficulty")
    recipe["prep_time"]  = rating.get("prep_time")
    if not recipe.get("source"):
        recipe["source"] = body.url

    return recipe


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
