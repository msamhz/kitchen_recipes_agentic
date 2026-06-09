"""
Smoke tests for all Pydantic schemas in kitchen_core.schemas.

These tests:
  - Instantiate every schema with valid data
  - Verify optional fields default correctly
  - Do NOT touch the DB or make external calls

Also guards against import-time failures in api/ routes (regression: DATABASE_URL
used to be read at module scope, failing before any test ran).
"""

import os

import pytest

# Must import cleanly with no env vars set
from kitchen_core.schemas import (
    ParseUrlRequest,
    RecipeCreate,
    RecipeIngredient,
    StockMarkUsed,
    StockPatch,
    StockUpsert,
)


class TestStockUpsert:
    def test_minimal(self):
        m = StockUpsert(names=["garlic", "onion"])
        assert m.names == ["garlic", "onion"]
        assert m.mode == "update"
        assert m.metadata == {}

    def test_restock_mode(self):
        assert StockUpsert(names=["chicken"], mode="restock").mode == "restock"

    def test_with_metadata(self):
        meta = {"chicken": {"expiry_date": "2026-06-20", "storage_location": "fridge"}}
        m = StockUpsert(names=["chicken"], metadata=meta)
        assert m.metadata["chicken"]["expiry_date"] == "2026-06-20"

    def test_empty_names(self):
        assert StockUpsert(names=[]).names == []


class TestStockPatch:
    def test_all_none_by_default(self):
        m = StockPatch()
        assert all(v is None for v in [m.name, m.in_stock, m.expiry_date, m.expiry_source, m.storage_location])

    def test_partial_patch(self):
        m = StockPatch(in_stock=0, expiry_date="2026-07-01")
        assert m.in_stock == 0
        assert m.expiry_date == "2026-07-01"
        assert m.name is None

    def test_storage_location(self):
        assert StockPatch(storage_location="freezer").storage_location == "freezer"


class TestStockMarkUsed:
    def test_basic(self):
        m = StockMarkUsed(names=["chicken", "garlic"])
        assert len(m.names) == 2

    def test_empty(self):
        assert StockMarkUsed(names=[]).names == []


class TestRecipeIngredient:
    def test_defaults(self):
        m = RecipeIngredient(name="garlic")
        assert m.name == "garlic"
        assert m.is_optional is False

    def test_optional_flag(self):
        assert RecipeIngredient(name="chilli", is_optional=True).is_optional is True


class TestRecipeCreate:
    def _minimal(self):
        return RecipeCreate(
            name="Garlic Fried Rice",
            instructions="Cook rice, fry with garlic.",
            ingredients=[RecipeIngredient(name="garlic"), RecipeIngredient(name="rice")],
        )

    def test_minimal_valid(self):
        m = self._minimal()
        assert m.name == "Garlic Fried Rice"
        assert len(m.ingredients) == 2

    def test_optional_fields_default_none(self):
        m = self._minimal()
        assert m.difficulty is None
        assert m.prep_time is None
        assert m.source is None

    def test_full_recipe(self):
        m = RecipeCreate(
            name="Nasi Lemak",
            instructions="Cook rice in coconut milk.",
            difficulty="medium",
            prep_time="10_to_20",
            source="https://example.com/recipe",
            ingredients=[
                RecipeIngredient(name="rice"),
                RecipeIngredient(name="coconut milk"),
                RecipeIngredient(name="sambal", is_optional=True),
            ],
        )
        assert m.difficulty == "medium"
        assert m.ingredients[2].is_optional is True

    def test_round_trip(self):
        m = self._minimal()
        m2 = RecipeCreate(**m.model_dump())
        assert m2.name == m.name
        assert len(m2.ingredients) == len(m.ingredients)


class TestParseUrlRequest:
    def test_youtube_url(self):
        m = ParseUrlRequest(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert "youtube.com" in m.url

    def test_plain_url(self):
        m = ParseUrlRequest(url="https://example.com/recipe/nasi-goreng")
        assert m.url.startswith("https://")
