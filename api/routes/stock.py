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
    in_stock: Optional[int] = None
    expiry_date: Optional[str] = None
    storage_location: Optional[str] = None


@router.get("")
def list_stock():
    """Return all ingredients with expiry and storage info."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, in_stock, expiry_date, storage_location, last_updated
        FROM ingredients
        ORDER BY name
    """)
    rows = cur.fetchall()
    conn.close()
    return {"ingredients": [dict(r) for r in rows]}


@router.post("/upsert")
def upsert_stock(body: StockUpsert):
    """Add or update ingredients after a scan confirmation."""
    conn = get_connection()
    cur = conn.cursor()
    upserted = []

    for name in body.names:
        meta = (body.metadata or {}).get(name, {})
        expiry = meta.get("expiry_date")
        storage = meta.get("storage_location")

        if body.mode == "restock":
            cur.execute("""
                INSERT INTO ingredients (name, in_stock, expiry_date, storage_location, last_updated)
                VALUES (%s, 1, %s, %s, NOW()::TEXT)
                ON CONFLICT (name) DO UPDATE SET
                    in_stock         = 1,
                    expiry_date      = COALESCE(EXCLUDED.expiry_date, ingredients.expiry_date),
                    storage_location = COALESCE(EXCLUDED.storage_location, ingredients.storage_location),
                    last_updated     = NOW()::TEXT
            """, (name, expiry, storage))
        else:
            cur.execute("""
                INSERT INTO ingredients (name, in_stock, expiry_date, storage_location, last_updated)
                VALUES (%s, 1, %s, %s, NOW()::TEXT)
                ON CONFLICT (name) DO UPDATE SET
                    expiry_date      = COALESCE(EXCLUDED.expiry_date, ingredients.expiry_date),
                    storage_location = COALESCE(EXCLUDED.storage_location, ingredients.storage_location),
                    last_updated     = NOW()::TEXT
            """, (name, expiry, storage))
        upserted.append(name)

    conn.commit()
    conn.close()
    return {"upserted": upserted, "count": len(upserted)}


@router.patch("/{ingredient_id}")
def patch_stock(ingredient_id: int, body: StockPatch):
    """Update in_stock, expiry_date, or storage_location for one ingredient."""
    conn = get_connection()
    cur = conn.cursor()

    fields, values = [], []
    if body.in_stock is not None:
        fields.append("in_stock = %s")
        values.append(body.in_stock)
    if body.expiry_date is not None:
        fields.append("expiry_date = %s")
        values.append(body.expiry_date)
    if body.storage_location is not None:
        fields.append("storage_location = %s")
        values.append(body.storage_location)

    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to update")

    fields.append("last_updated = NOW()::TEXT")
    values.append(ingredient_id)

    cur.execute(
        f"UPDATE ingredients SET {', '.join(fields)} WHERE id = %s",
        values,
    )
    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Ingredient not found")

    conn.commit()
    conn.close()
    return {"updated": ingredient_id}


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
