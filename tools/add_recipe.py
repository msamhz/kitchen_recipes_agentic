"""
Recipe Ingest Tool
-------------------
Accepts a recipe as plain text OR a URL, parses it with Claude,
and writes it into kitchen.db (recipes + recipe_ingredients tables).

Usage:
    python tools/add_recipe.py --text "Spaghetti Bolognese\n\nIngredients: ..."
    python tools/add_recipe.py --url "https://www.example.com/recipe/spaghetti"
    python tools/add_recipe.py --file recipes/bolognese.txt
"""

import argparse
import concurrent.futures
import json
import os
import sys

import urllib3
import requests
from bs4 import BeautifulSoup
import yt_dlp

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}

sys.path.insert(0, os.path.dirname(__file__))
from db_init import get_connection, init_db
from clients import sync_client as client

PARSE_PROMPT = """You are a recipe parser. Extract the recipe from the text below.

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


RATE_PROMPT = """You are rating a recipe for a kitchen assistant app.

Recipe name: {name}
Instructions:
{instructions}

Determine:
1. difficulty — easy | medium | hard
   easy: few steps, no special technique, beginner-friendly
   medium: multiple steps, some timing or technique needed
   hard: advanced technique, complex steps, requires experience

2. prep_time — under_10 | 10_to_20 | over_20
   Active hands-on preparation time only (exclude passive time like marinating or long simmering).
   under_10: less than 10 minutes
   10_to_20: 10 to 20 minutes
   over_20: more than 20 minutes

If the text doesn't provide enough detail, use your knowledge of this type of dish to estimate.

Return ONLY valid JSON, no markdown:
{{"difficulty": "easy|medium|hard", "prep_time": "under_10|10_to_20|over_20"}}
"""


def _is_youtube(url: str) -> bool:
    from urllib.parse import urlparse
    return urlparse(url).hostname in _YOUTUBE_HOSTS


def _fetch_youtube(url: str) -> str:
    print(f"[Fetch] YouTube — extracting metadata: {url}")
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True, "nocheckcertificate": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    title = info.get("title", "")
    description = info.get("description", "")
    if not description:
        raise ValueError("No description found in YouTube video — the channel may not include a recipe.")

    # Cap combined text to 8k chars; description usually has the recipe
    text = f"Video title: {title}\n\n{description}"
    return text[:8000]


def fetch_url(url: str) -> str:
    if _is_youtube(url):
        return _fetch_youtube(url)

    print(f"[Fetch] {url}")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; KitchenBot/1.0)"}
    resp = requests.get(url, headers=headers, timeout=15, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)[:8000]


def parse_recipe(text: str, source: str | None = None) -> dict:
    print("[Claude] Parsing recipe...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": PARSE_PROMPT.format(text=text)}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    recipe = json.loads(raw.strip())
    if source and not recipe.get("source"):
        recipe["source"] = source
    return recipe


def rate_recipe(text: str, name: str = "") -> dict:
    print("[Claude] Rating difficulty and prep time...")
    # Use first 4000 chars of instructions — enough for rating
    instructions = text[:4000]
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=128,
        messages=[{"role": "user", "content": RATE_PROMPT.format(name=name, instructions=instructions)}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result = json.loads(raw.strip())
        valid_diff = {"easy", "medium", "hard"}
        valid_time = {"under_10", "10_to_20", "over_20"}
        return {
            "difficulty": result.get("difficulty") if result.get("difficulty") in valid_diff else None,
            "prep_time": result.get("prep_time") if result.get("prep_time") in valid_time else None,
        }
    except (json.JSONDecodeError, AttributeError):
        return {"difficulty": None, "prep_time": None}


def save_recipe(recipe: dict) -> int:
    conn = get_connection()
    cur = conn.cursor()

    # Upsert recipe
    cur.execute(
        """
        INSERT INTO recipes (name, instructions, source, difficulty, prep_time)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            instructions = excluded.instructions,
            source = excluded.source,
            difficulty = excluded.difficulty,
            prep_time = excluded.prep_time
        """,
        (recipe["name"], recipe["instructions"], recipe.get("source"),
         recipe.get("difficulty"), recipe.get("prep_time")),
    )
    cur.execute("SELECT id FROM recipes WHERE name = ?", (recipe["name"],))
    recipe_id = cur.fetchone()["id"]

    # Clear old ingredient links for this recipe (re-linking below)
    cur.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (recipe_id,))

    for ing in recipe.get("ingredients", []):
        name = ing["name"].strip().lower()
        # Upsert ingredient (in_stock left unchanged if already exists)
        cur.execute(
            """
            INSERT INTO ingredients (name, in_stock)
            VALUES (?, 0)
            ON CONFLICT(name) DO NOTHING
            """,
            (name,),
        )
        cur.execute("SELECT id FROM ingredients WHERE name = ?", (name,))
        ing_id = cur.fetchone()["id"]

        cur.execute(
            "INSERT INTO recipe_ingredients (recipe_id, ingredient_id, is_optional) VALUES (?, ?, ?)",
            (recipe_id, ing_id, 1 if ing.get("is_optional") else 0),
        )

    conn.commit()
    conn.close()
    return recipe_id


def run(text: str | None = None, url: str | None = None, file: str | None = None):
    init_db()

    source = url
    if url:
        text = fetch_url(url)
    elif file:
        with open(file, "r", encoding="utf-8") as f:
            text = f.read()

    if not text:
        print("ERROR: No recipe input provided.")
        sys.exit(1)

    # Parse and rate run in parallel — both only need the raw text
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        parse_future = pool.submit(parse_recipe, text, source)
        rate_future = pool.submit(rate_recipe, text)
        recipe = parse_future.result()
        rating = rate_future.result()

    recipe["difficulty"] = rating.get("difficulty")
    recipe["prep_time"] = rating.get("prep_time")

    recipe_id = save_recipe(recipe)

    diff_label = recipe.get("difficulty") or "?"
    time_label = {"under_10": "<10 min", "10_to_20": "10-20 min", "over_20": ">20 min"}.get(recipe.get("prep_time"), "?")
    print(f"\n[DB] Saved recipe: '{recipe['name']}' (id={recipe_id}) — {diff_label} / {time_label}")
    print(f"     Ingredients ({len(recipe['ingredients'])}):")
    for ing in recipe["ingredients"]:
        optional = " (optional)" if ing.get("is_optional") else ""
        print(f"       - {ing['name']}{optional}")

    return recipe_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recipe Ingest Tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Recipe as plain text")
    group.add_argument("--url", help="URL of a recipe page")
    group.add_argument("--file", help="Path to a text file containing the recipe")
    args = parser.parse_args()
    run(text=args.text, url=args.url, file=args.file)
