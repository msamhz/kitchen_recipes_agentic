"""
Unit tests for kitchen_core.shelf_life — pure functions, no mocking needed.
"""

from datetime import date, timedelta

import pytest

from kitchen_core.shelf_life import STORAGE_OPTIONS, get_default_expiry, get_storage_guess


class TestGetDefaultExpiry:
    def test_returns_none_for_unknown_ingredient(self):
        assert get_default_expiry("unobtainium", "fridge") is None

    def test_returns_date_object_for_known_ingredient(self):
        assert isinstance(get_default_expiry("chicken", "fridge"), date)

    def test_chicken_fridge_is_2_days(self):
        assert get_default_expiry("chicken breast", "fridge") == date.today() + timedelta(days=2)

    def test_chicken_freezer_is_270_days(self):
        assert get_default_expiry("chicken", "freezer") == date.today() + timedelta(days=270)

    def test_rice_pantry_is_730_days(self):
        assert get_default_expiry("beras", "pantry") == date.today() + timedelta(days=730)

    def test_returns_none_when_no_estimate_for_storage(self):
        assert get_default_expiry("chicken", "pantry") is None
        assert get_default_expiry("chicken", "counter") is None

    def test_invalid_storage_falls_back_to_pantry(self):
        assert get_default_expiry("rice", "shelf") == get_default_expiry("rice", "pantry")

    def test_multilingual_malay(self):
        assert get_default_expiry("telur", "fridge") == date.today() + timedelta(days=35)

    def test_longer_keyword_wins_fish_sauce_vs_fish(self):
        result = get_default_expiry("fish sauce", "pantry")
        assert result == date.today() + timedelta(days=365)

    def test_all_storage_options_accepted(self):
        for loc in STORAGE_OPTIONS:
            get_default_expiry("egg", loc)  # should not raise


class TestGetStorageGuess:
    def test_returns_valid_location(self):
        assert get_storage_guess("garlic") in STORAGE_OPTIONS

    def test_chicken_is_fridge(self):
        assert get_storage_guess("chicken breast") == "fridge"

    def test_rice_is_pantry(self):
        assert get_storage_guess("rice") == "pantry"

    def test_frozen_prefix_always_freezer(self):
        assert get_storage_guess("frozen peas") == "freezer"
        assert get_storage_guess("frozen chicken") == "freezer"

    def test_fish_sauce_is_pantry_not_fridge(self):
        assert get_storage_guess("fish sauce") == "pantry"
        assert get_storage_guess("tiparos fish sauce") == "pantry"

    def test_generic_fish_is_fridge(self):
        assert get_storage_guess("ikan bilis") == "fridge"

    def test_tomato_sauce_is_pantry_not_counter(self):
        assert get_storage_guess("tomato sauce") == "pantry"

    def test_banana_is_counter(self):
        assert get_storage_guess("banana") == "counter"

    def test_unknown_defaults_to_pantry(self):
        assert get_storage_guess("mystery_ingredient_xyz") == "pantry"

    def test_egg_is_fridge(self):
        assert get_storage_guess("egg") == "fridge"
        assert get_storage_guess("telur") == "fridge"
