import asyncio
import base64
import io

from fastapi import APIRouter, UploadFile, File, HTTPException
from PIL import Image

from kitchen_core.clients import async_client
from kitchen_core.cv import IDENTIFY_PROMPT, parse_cv_response, _MAX_B64_BYTES
from kitchen_core.shelf_life import get_default_expiry, get_storage_guess

router = APIRouter()


def _compress_bytes(raw: bytes) -> tuple[str, str]:
    """Compress raw image bytes to fit Claude's 5MB base64 limit. Returns (b64, media_type)."""
    if len(base64.standard_b64encode(raw)) <= _MAX_B64_BYTES:
        return base64.standard_b64encode(raw).decode(), "image/jpeg"

    img = Image.open(io.BytesIO(raw)).convert("RGB")
    for quality in range(85, 15, -15):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(base64.standard_b64encode(data)) <= _MAX_B64_BYTES:
            return base64.standard_b64encode(data).decode(), "image/jpeg"

    img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return base64.standard_b64encode(buf.getvalue()).decode(), "image/jpeg"


async def _scan_one(raw: bytes) -> dict:
    """Send one image to Claude, return parsed ingredients dict."""
    b64, media_type = _compress_bytes(raw)
    response = await async_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": IDENTIFY_PROMPT},
            ],
        }],
    )
    return parse_cv_response(response.content[0].text)


@router.post("")
async def scan(files: list[UploadFile] = File(...)):
    """
    Scan 1+ kitchen photos with Claude vision.
    Returns candidate ingredients with expiry dates and storage suggestions.
    Does NOT save to DB — call POST /stock/upsert to confirm.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No images provided")

    raw_images = [await f.read() for f in files]
    results = await asyncio.gather(*[_scan_one(raw) for raw in raw_images])

    seen: dict[str, dict] = {}
    for result in results:
        for item in result.get("ingredients", []):
            name = item["name"].strip().lower()
            if name and name not in seen:
                seen[name] = item

    candidates = []
    for name, item in seen.items():
        if item.get("confidence", "low") == "low":
            continue

        storage = get_storage_guess(name)
        cv_expiry = item.get("expiry_date")

        if cv_expiry:
            expiry = cv_expiry
            expiry_source = "label"
        else:
            kb_date = get_default_expiry(name, storage)
            expiry = kb_date.isoformat() if kb_date else None
            expiry_source = "estimate" if expiry else None

        candidates.append({
            "name": name,
            "confidence": item.get("confidence", "medium"),
            "expiry_date": expiry,
            "expiry_source": expiry_source,
            "storage_location": storage,
            "notes": item.get("notes", ""),
        })

    return {"candidates": candidates, "count": len(candidates)}
