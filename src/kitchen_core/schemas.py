"""
Shared Pydantic schemas — single source of truth for the data model.
Used by API routes, agents, and DB writes.
"""

from typing import Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Recipe
# ---------------------------------------------------------------------------

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


class ParseUrlRequest(BaseModel):
    url: str


# ---------------------------------------------------------------------------
# Stock / Ingredients
# ---------------------------------------------------------------------------

class StockUpsert(BaseModel):
    names: list[str]
    mode: str = "update"  # "update" | "restock"
    metadata: Optional[dict] = {}


class StockPatch(BaseModel):
    name: Optional[str] = None
    in_stock: Optional[int] = None
    expiry_date: Optional[str] = None
    expiry_source: Optional[str] = None
    storage_location: Optional[str] = None


class StockMarkUsed(BaseModel):
    names: list[str]
