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
import json
import os
import sys

import requests
from bs4 import BeautifulSoup

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


def fetch_url(url: str) -> str:
    print(f"[Fetch] {url}")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; KitchenBot/1.0)"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    # Remove script/style noise
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)[:8000]  # cap at 8k chars


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


def save_recipe(recipe: dict) -> int:
    conn = get_connection()
    cur = conn.cursor()

    # Upsert recipe
    cur.execute(
        """
        INSERT INTO recipes (name, instructions, source)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            instructions = excluded.instructions,
            source = excluded.source
        """,
        (recipe["name"], recipe["instructions"], recipe.get("source")),
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

    recipe = parse_recipe(text, source=source)
    recipe_id = save_recipe(recipe)

    print(f"\n[DB] Saved recipe: '{recipe['name']}' (id={recipe_id})")
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
