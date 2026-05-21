from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from api.db import get_connection

router = APIRouter()


class StockUpsert(BaseModel):
    names: list[str]
    mode: str = "update"           # "update" | "restock"
    metadata: Optional[dict] = {}  # {name: {expiry_date, storage_location}}


class StockPatch(BaseModel):
    name: Optional[str] = None
    in_stock: Optional[int] = None
    expiry_date: Optional[str] = None
    expiry_source: Optional[str] = None
    storage_location: Optional[str] = None


@router.get("")
def list_stock():
    """Return all ingredients with expiry and storage info."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, in_stock, expiry_date, expiry_source, storage_location, last_updated
        FROM ingredients
        ORDER BY name
    """)
    rows = cur.fetchall()
    conn.close()
    return {"ingredients": [dict(r) for r in rows]}


@router.post("/upsert")
async def upsert_stock(body: StockUpsert):
    """Add or update ingredients after scan confirmation.
    Names are normalised via vector similarity before saving to avoid duplicates."""
    from api.normalise import normalise_ingredient, get_index

    conn = get_connection()
    cur = conn.cursor()
    upserted = []
    seen: set[str] = set()
    index = get_index()

    for orig_name in body.names:
        canonical = normalise_ingredient(orig_name.strip().lower())
        if canonical in seen:
            continue
        seen.add(canonical)

        # Metadata is keyed by original name from the frontend; fall back to canonical
        meta = (body.metadata or {}).get(orig_name) or (body.metadata or {}).get(canonical) or {}
        expiry        = meta.get("expiry_date")
        expiry_source = meta.get("expiry_source")
        storage       = meta.get("storage_location")

        if body.mode == "restock":
            cur.execute("""
                INSERT INTO ingredients (name, in_stock, expiry_date, expiry_source, storage_location, last_updated)
                VALUES (%s, 1, %s, %s, %s, NOW()::TEXT)
                ON CONFLICT (name) DO UPDATE SET
                    in_stock         = 1,
                    expiry_date      = COALESCE(EXCLUDED.expiry_date, ingredients.expiry_date),
                    expiry_source    = COALESCE(EXCLUDED.expiry_source, ingredients.expiry_source),
                    storage_location = COALESCE(EXCLUDED.storage_location, ingredients.storage_location),
                    last_updated     = NOW()::TEXT
            """, (canonical, expiry, expiry_source, storage))
        else:
            cur.execute("""
                INSERT INTO ingredients (name, in_stock, expiry_date, expiry_source, storage_location, last_updated)
                VALUES (%s, 1, %s, %s, %s, NOW()::TEXT)
                ON CONFLICT (name) DO UPDATE SET
                    expiry_date      = COALESCE(EXCLUDED.expiry_date, ingredients.expiry_date),
                    expiry_source    = COALESCE(EXCLUDED.expiry_source, ingredients.expiry_source),
                    storage_location = COALESCE(EXCLUDED.storage_location, ingredients.storage_location),
                    last_updated     = NOW()::TEXT
            """, (canonical, expiry, expiry_source, storage))

        # Persist embedding for new ingredients so future scans can match against them
        if canonical not in index.names:
            try:
                index.embed_and_save(canonical)
            except Exception:
                pass

        upserted.append(canonical)

    conn.commit()
    conn.close()
    return {"upserted": upserted, "count": len(upserted)}


@router.patch("/{ingredient_id}")
def patch_stock(ingredient_id: int, body: StockPatch):
    """Update in_stock, expiry_date, or storage_location for one ingredient."""
    conn = get_connection()
    cur = conn.cursor()

    fields, values = [], []
    if body.name is not None:
        trimmed = body.name.strip().lower()
        if not trimmed:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        fields.append("name = %s")
        values.append(trimmed)
    if body.in_stock is not None:
        fields.append("in_stock = %s")
        values.append(body.in_stock)
    if body.expiry_date is not None:
        fields.append("expiry_date = %s")
        values.append(body.expiry_date)
    if body.expiry_source is not None:
        fields.append("expiry_source = %s")
        values.append(body.expiry_source)
    if body.storage_location is not None:
        fields.append("storage_location = %s")
        values.append(body.storage_location)

    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to update")

    fields.append("last_updated = NOW()::TEXT")
    values.append(ingredient_id)

    try:
        cur.execute(
            f"UPDATE ingredients SET {', '.join(fields)} WHERE id = %s",
            values,
        )
    except Exception as e:
        conn.close()
        if "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="Name already exists")
        raise HTTPException(status_code=500, detail=str(e))

    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Ingredient not found")

    conn.commit()
    conn.close()
    return {"updated": ingredient_id}


class StockMarkUsed(BaseModel):
    names: list[str]


@router.post("/mark-used")
def mark_used(body: StockMarkUsed):
    """Mark a list of ingredient names as out of stock (used when cooking)."""
    conn = get_connection()
    cur = conn.cursor()
    updated = []
    for name in body.names:
        cur.execute(
            "UPDATE ingredients SET in_stock = 0, last_updated = NOW()::TEXT WHERE name = %s",
            (name,),
        )
        if cur.rowcount > 0:
            updated.append(name)
    conn.commit()
    conn.close()
    return {"updated": updated, "count": len(updated)}


@router.delete("/{ingredient_id}")
def delete_stock(ingredient_id: int):
    """Remove an ingredient from stock."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM ingredients WHERE id = %s", (ingredient_id,))
    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Ingredient not found")
    conn.commit()
    conn.close()
    return {"deleted": ingredient_id}
