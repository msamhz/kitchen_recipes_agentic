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
from normalise import normalise_batch_async, get_existing_ingredient_names
from ingredient_index import get_index

IDENTIFY_PROMPT = """You are a kitchen inventory assistant with excellent food recognition skills.

Analyze this image carefully and identify ALL food ingredients visible.
Include: fresh produce, packaged goods, condiments, spices, dairy, meat, beverages, dry goods.

For each item, provide:
- name: common ingredient name (e.g. "chicken breast", "garlic", "soy sauce")
- confidence: "high", "medium", or "low"
- notes: brief note if uncertain (e.g. "blurry label", "similar to X")
- expiry_date: search the packaging carefully for a date. Return it as "YYYY-MM-DD" if clearly readable, else null.

EXPIRY DATE — WHERE TO LOOK BY PACKAGE TYPE:
- Bottles (sauce, fish sauce, soy sauce, oil): ** PRIORITY: inspect the CAP ITSELF first **
    → TOP FACE of the cap (look straight down at it — date is often ink-jetted or laser-stamped here)
    → SIDE BAND of the cap (the cylindrical rim, may have "EXP DD/MM/YY" stamped in small font)
    → Neck of the bottle just BELOW the cap
    → BOTTOM of the bottle (embossed or ink-jetted)
    → Top or bottom edge of the front label
  NOTE: for Southeast Asian sauce bottles (Singapore/Malaysia/Thailand) the cap is the #1 location.
  A lone date printed on the cap with NO keyword prefix IS the expiry date — caps don't carry manufacture dates.
- Cans / tins: embossed on the TOP rim or BOTTOM rim; sometimes on the side label
- Cartons (milk, juice, broth): printed on the TOP flap, the side panel, or near the pour spout
- Plastic pouches / sachets: along the HEAT-SEALED edges (top or bottom seam)
- Jars (paste, jam, sambal): underside of the LID or the bottom of the jar
- Dairy tubs / yogurt: on the FOIL SEAL or the bottom of the tub
- Bags (flour, rice, frozen goods): printed or stamped near the CLOSURE or on the back panel
- Eggs: stamped on the shell or on the tray
- Fresh produce (packaged): on the STICKER or TRAY LABEL

COMMON DATE LABEL KEYWORDS (look for these near any date):
- English: EXP, EXPIRY, BEST BEFORE, BB, USE BY, USE BEFORE, BBE, SELL BY
- Malay: TARIKH LUPUT, LUPUT, GUNAKAN SEBELUM, BAIK SEBELUM
- Chinese: 到期日, 保质期至, 最佳食用期, 生产日期 (manufacture date — ignore this one)
- No keyword: a date printed alone on the cap or lid is ALWAYS the expiry — treat it as such.

DATE FORMAT RULES — Singapore/Malaysia products almost always use DD/MM/YY or DD/MM/YYYY:
- DD/MM/YY  → day first, e.g. 18/05/26 = 2026-05-18  (NOT May 18 interpreted as US MM/DD)
- DD/MM/YYYY → e.g. 31/10/2025 = 2025-10-31
- MM/YY with no day → use the last day of that month: 05/26 = 2026-05-31
- MON YYYY → use the last day: "MAY 2026" = 2026-05-31
- YYYY-MM-DD → already ISO, use as-is
Convert whatever format you read to YYYY-MM-DD.

BATCH/LOT CODE vs DATE — do NOT confuse these:
- Batch codes look like: 42019696PC, L2304A, MFG2024083, 09 04 0001  — alphanumeric, NOT dates
- A real date has a recognisable day/month/year pattern (numbers between 01-31 / 01-12 / 20xx or YY)
- If you see both a date AND a batch code near each other, only return the date

Only return a date if you can read it clearly. Do NOT guess. If the date is partially obscured, return null.

Return ONLY valid JSON in this exact format:
{
  "ingredients": [
    {"name": "...", "confidence": "high|medium|low", "notes": "...", "expiry_date": "YYYY-MM-DD or null"},
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


def upsert_ingredients(
    names: list[str],
    mode: str = "update",
    metadata: "dict[str, dict] | None" = None,
):
    """
    mode='update': only set in_stock=1 for detected items, leave others unchanged.
    mode='restock': set in_stock=1 for detected items, set in_stock=0 for all others
                    (full replace — what's in the photo IS the current stock).
    metadata: optional dict mapping name -> {"expiry_date": "YYYY-MM-DD"|None,
                                              "storage_location": str|None}
    """
    from embeddings import encode
    from ingredient_index import _vec_to_blob

    index = get_index()
    names = [n.strip().lower() for n in names]
    meta = metadata or {}

    # Pre-compute embeddings for new ingredients BEFORE opening the DB connection
    # so we never have two connections open simultaneously (SQLite single-writer).
    to_embed = {n: encode(n) for n in names if n not in index.names}

    conn = get_connection()
    cur = conn.cursor()

    if mode == "restock":
        cur.execute("UPDATE ingredients SET in_stock = 0, last_updated = datetime('now')")

    for name in names:
        m = meta.get(name, {})
        expiry = m.get("expiry_date") or None
        storage = m.get("storage_location") or None
        cur.execute(
            """
            INSERT INTO ingredients (name, in_stock, last_updated, expiry_date, storage_location)
            VALUES (?, 1, datetime('now'), ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                in_stock = 1,
                last_updated = datetime('now'),
                expiry_date = COALESCE(excluded.expiry_date, expiry_date),
                storage_location = COALESCE(excluded.storage_location, storage_location)
            """,
            (name, expiry, storage),
        )
        if name in to_embed:
            cur.execute(
                "UPDATE ingredients SET embedding = ? WHERE name = ?",
                (_vec_to_blob(to_embed[name]), name),
            )

    conn.commit()
    conn.close()

    # Update in-memory index only after the connection is fully closed
    for name, vec in to_embed.items():
        index.add(name, vec)


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
        existing = get_existing_ingredient_names()
        print(f"[Normalise] Checking {len(confirmed_names)} ingredient(s) against {len(existing)} in DB...")
        confirmed_names = await normalise_batch_async(confirmed_names, existing)
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
