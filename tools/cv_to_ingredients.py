"""
CV to Ingredients DB Tool
--------------------------
Takes an image path, uses Claude vision to identify ingredients,
optionally web-searches uncertain items, then upserts into kitchen.db.

Usage:
    python tools/cv_to_ingredients.py --image path/to/photo.jpg
    python tools/cv_to_ingredients.py --image path/to/photo.jpg --mode restock
"""

import argparse
import asyncio
import base64
import io
import json
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from db_init import get_connection, init_db
from clients import sync_client as client, async_client

IDENTIFY_PROMPT = """You are a kitchen inventory assistant with excellent food recognition skills.

Analyze this image carefully and identify ALL food ingredients visible.
Include: fresh produce, packaged goods, condiments, spices, dairy, meat, beverages, dry goods.

For each item, provide:
- name: common ingredient name (e.g. "chicken breast", "garlic", "soy sauce")
- confidence: "high", "medium", or "low"
- notes: brief note if uncertain (e.g. "blurry label", "similar to X")

Return ONLY valid JSON in this exact format:
{
  "ingredients": [
    {"name": "...", "confidence": "high|medium|low", "notes": "..."},
    ...
  ],
  "uncertain": ["item1", "item2"]
}

"uncertain" lists items where you need a web search to confirm what they are.
"""

WEB_CLARIFY_PROMPT = """A kitchen photo showed an unknown item described as: "{description}"

Based on your knowledge, what is the most likely common food ingredient this refers to?
Reply with ONLY a JSON object:
{{"resolved_name": "ingredient name", "confidence": "high|medium|low"}}
"""


_MAX_B64_BYTES = 4_800_000  # Claude limit is 5 MB base64; leave headroom

def encode_image(image_path: str) -> tuple[str, str]:
    ext = os.path.splitext(image_path)[1].lower()
    media_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    media_type = media_map.get(ext, "image/jpeg")

    with open(image_path, "rb") as f:
        raw = f.read()

    # Fast path: already small enough
    if len(base64.standard_b64encode(raw)) <= _MAX_B64_BYTES:
        return base64.standard_b64encode(raw).decode("utf-8"), media_type

    # Compress with Pillow until it fits
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    quality = 85
    while quality >= 30:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(base64.standard_b64encode(data)) <= _MAX_B64_BYTES:
            print(f"[CV] Compressed image to {len(data)//1024}KB (quality={quality})")
            return base64.standard_b64encode(data).decode("utf-8"), "image/jpeg"
        quality -= 15

    # Last resort: halve resolution then compress
    img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    data = buf.getvalue()
    print(f"[CV] Resized + compressed image to {len(data)//1024}KB")
    return base64.standard_b64encode(data).decode("utf-8"), "image/jpeg"


def _parse_cv_response(raw: str) -> dict:
    """Parse Claude's JSON response, recovering gracefully from truncation."""
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Response was cut off — extract whatever complete ingredient objects exist
        import re
        names = re.findall(r'"name"\s*:\s*"([^"]+)"', raw)
        print(f"[CV] Warning: JSON truncated, recovered {len(names)} ingredient names")
        return {
            "ingredients": [{"name": n, "confidence": "medium", "notes": ""} for n in names],
            "uncertain": [],
        }


def identify_ingredients(image_path: str) -> dict:
    print(f"[CV] Analyzing image: {image_path}")
    image_data, media_type = encode_image(image_path)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                    {"type": "text", "text": IDENTIFY_PROMPT},
                ],
            }
        ],
    )

    return _parse_cv_response(response.content[0].text)


def resolve_uncertain(description: str) -> str | None:
    print(f"[CV] Resolving uncertain item: '{description}'")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=128,
        messages=[{"role": "user", "content": WEB_CLARIFY_PROMPT.format(description=description)}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result = json.loads(raw.strip())
        if result.get("confidence") in ("high", "medium"):
            return result["resolved_name"]
    except json.JSONDecodeError:
        pass
    return None


async def identify_ingredients_async(image_path: str) -> dict:
    print(f"[CV] Analyzing image (async): {image_path}")
    image_data, media_type = encode_image(image_path)

    response = await async_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                    {"type": "text", "text": IDENTIFY_PROMPT},
                ],
            }
        ],
    )
    return _parse_cv_response(response.content[0].text)


DEDUP_PROMPT = """You are deduplicating a kitchen ingredient list before saving to a database.

Newly detected ingredients:
{candidates}

Ingredients already in the database (prefer these names if same ingredient):
{existing}

Rules:
- Merge items that are clearly the same physical ingredient (e.g. "sesame oil" and "sesame oil (second bottle)" → "sesame oil")
- Only merge when you are highly confident — different brands of the same sauce are the SAME ingredient
- If a DB name matches a detected item, use the DB name as the canonical name
- Keep all genuinely distinct ingredients separate
- Return the final deduplicated list as a JSON array of strings

Return ONLY: {{"ingredients": ["name1", "name2", ...]}}
"""


async def deduplicate_async(candidates: list[str], existing: list[str]) -> list[str]:
    if len(candidates) <= 1:
        return candidates

    response = await async_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": DEDUP_PROMPT.format(
                candidates=json.dumps(candidates),
                existing=json.dumps(existing),
            ),
        }],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw.strip())
        result = [n.strip().lower() for n in data.get("ingredients", []) if n.strip()]
        return result if result else candidates
    except (json.JSONDecodeError, AttributeError):
        return candidates


async def resolve_uncertain_async(description: str) -> str | None:
    print(f"[CV] Resolving uncertain item (async): '{description}'")
    response = await async_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=128,
        messages=[{"role": "user", "content": WEB_CLARIFY_PROMPT.format(description=description)}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result = json.loads(raw.strip())
        if result.get("confidence") in ("high", "medium"):
            return result["resolved_name"]
    except json.JSONDecodeError:
        pass
    return None


def upsert_ingredients(names: list[str], mode: str = "update"):
    """
    mode='update': only set in_stock=1 for detected items, leave others unchanged.
    mode='restock': set in_stock=1 for detected items, set in_stock=0 for all others
                    (full replace — what's in the photo IS the current stock).
    """
    conn = get_connection()
    cur = conn.cursor()

    if mode == "restock":
        # Mark everything out of stock first, then re-enable what was found
        cur.execute("UPDATE ingredients SET in_stock = 0, last_updated = datetime('now')")

    for name in names:
        cur.execute(
            """
            INSERT INTO ingredients (name, in_stock, last_updated)
            VALUES (?, 1, datetime('now'))
            ON CONFLICT(name) DO UPDATE SET
                in_stock = 1,
                last_updated = datetime('now')
            """,
            (name.strip().lower(),),
        )

    conn.commit()
    conn.close()


def run(image_path: str, mode: str = "update"):
    if not os.path.exists(image_path):
        print(f"ERROR: Image not found: {image_path}")
        sys.exit(1)

    init_db()

    result = identify_ingredients(image_path)
    ingredients = result.get("ingredients", [])
    uncertain = result.get("uncertain", [])

    confirmed_names = []

    for item in ingredients:
        if item["confidence"] in ("high", "medium"):
            confirmed_names.append(item["name"])
            print(f"  [+] {item['name']} ({item['confidence']})")
        else:
            print(f"  [?] {item['name']} — low confidence, attempting resolution...")
            resolved = resolve_uncertain(item.get("notes", item["name"]))
            if resolved:
                confirmed_names.append(resolved)
                print(f"      -> resolved to: {resolved}")
            else:
                print(f"      -> skipped (could not resolve)")

    for desc in uncertain:
        print(f"  [?] Uncertain: '{desc}' — attempting web resolution...")
        resolved = resolve_uncertain(desc)
        if resolved:
            confirmed_names.append(resolved)
            print(f"      -> resolved to: {resolved}")
        else:
            print(f"      -> skipped")

    if confirmed_names:
        upsert_ingredients(confirmed_names, mode=mode)
        print(f"\n[DB] Upserted {len(confirmed_names)} ingredients (mode={mode})")
    else:
        print("\n[DB] No ingredients to save.")

    return confirmed_names


async def run_async(image_path: str, mode: str = "update"):
    if not os.path.exists(image_path):
        print(f"ERROR: Image not found: {image_path}")
        sys.exit(1)

    init_db()

    result = await identify_ingredients_async(image_path)
    ingredients = result.get("ingredients", [])
    uncertain = result.get("uncertain", [])

    confirmed_names = []
    to_resolve = []

    for item in ingredients:
        if item["confidence"] in ("high", "medium"):
            confirmed_names.append(item["name"])
            print(f"  [+] {item['name']} ({item['confidence']})")
        else:
            print(f"  [?] {item['name']} — low confidence, queued for resolution...")
            to_resolve.append(item.get("notes", item["name"]))

    for desc in uncertain:
        print(f"  [?] Uncertain: '{desc}' — queued for resolution...")

    all_to_resolve = to_resolve + list(uncertain)
    if all_to_resolve:
        print(f"[CV] Resolving {len(all_to_resolve)} uncertain item(s) in parallel...")
        resolved_results = await asyncio.gather(
            *[resolve_uncertain_async(desc) for desc in all_to_resolve]
        )
        for desc, resolved in zip(all_to_resolve, resolved_results):
            if resolved:
                confirmed_names.append(resolved)
                print(f"      -> '{desc}' resolved to: {resolved}")
            else:
                print(f"      -> '{desc}' skipped (could not resolve)")

    if confirmed_names:
        upsert_ingredients(confirmed_names, mode=mode)
        print(f"\n[DB] Upserted {len(confirmed_names)} ingredients (mode={mode})")
    else:
        print("\n[DB] No ingredients to save.")

    return confirmed_names


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CV to Ingredients DB")
    parser.add_argument("--image", required=True, help="Path to kitchen photo")
    parser.add_argument(
        "--mode",
        choices=["update", "restock"],
        default="update",
        help="update: add detected items; restock: replace entire stock with what's in photo",
    )
    args = parser.parse_args()
    asyncio.run(run_async(args.image, args.mode))
