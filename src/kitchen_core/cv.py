"""
CV (computer vision) helpers for kitchen scanning.

Provides the Claude prompt and response parser used by the scan endpoint.
No DB or client imports here — pure constants and parsing logic.
"""

import json
import re

_MAX_B64_BYTES = 4_800_000  # Claude limit is 5 MB base64; leave headroom

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


def parse_cv_response(raw: str) -> dict:
    """Parse Claude's JSON response, recovering gracefully from truncation."""
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        names = re.findall(r'"name"\s*:\s*"([^"]+)"', raw)
        print(f"[CV] Warning: JSON truncated, recovered {len(names)} ingredient names")
        return {
            "ingredients": [{"name": n, "confidence": "medium", "notes": ""} for n in names],
            "uncertain": [],
        }


# Backward-compat alias used by tools/cv_to_ingredients.py imports
_parse_cv_response = parse_cv_response
