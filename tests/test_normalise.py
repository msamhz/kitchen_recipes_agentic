"""
Unit tests for kitchen_core.normalise.

The IngredientIndex and LLM calls are mocked so:
  - No Neon connection required
  - No Anthropic API key required
  - Tests run fully offline
"""

from unittest.mock import MagicMock, patch

import pytest

from kitchen_core.normalise import (
    _fmt_neighbours,
    _parse_grey,
    normalise_batch_async,
    normalise_ingredient,
)


# ---------------------------------------------------------------------------
# Pure helpers — no mocking required
# ---------------------------------------------------------------------------

class TestFmtNeighbours:
    def test_formats_top_3(self):
        neighbours = [("fish sauce", 0.92), ("oyster sauce", 0.80), ("soy sauce", 0.76), ("vinegar", 0.60)]
        result = _fmt_neighbours(neighbours)
        lines = result.splitlines()
        assert len(lines) == 3
        assert '"fish sauce"' in lines[0]
        assert "0.92" in lines[0]
        assert '"oyster sauce"' in lines[1]

    def test_empty_neighbours(self):
        assert _fmt_neighbours([]) == ""


class TestParseGrey:
    def test_valid_match_returned(self):
        raw = '{"match_index": 1, "canonical": "fish sauce"}'
        neighbours = [("fish sauce", 0.82)]
        assert _parse_grey(raw, neighbours) == "fish sauce"

    def test_null_match_returns_none(self):
        raw = '{"match_index": null, "canonical": null}'
        assert _parse_grey(raw, [("fish sauce", 0.82)]) is None

    def test_canonical_not_in_neighbours_returns_none(self):
        raw = '{"match_index": 1, "canonical": "unknown_thing"}'
        assert _parse_grey(raw, [("fish sauce", 0.82)]) is None

    def test_strips_markdown_fences(self):
        raw = '```json\n{"match_index": 1, "canonical": "garlic"}\n```'
        assert _parse_grey(raw, [("garlic", 0.83)]) == "garlic"

    def test_invalid_json_returns_none(self):
        assert _parse_grey("not json", [("garlic", 0.83)]) is None


# ---------------------------------------------------------------------------
# normalise_ingredient — mock the index so no DB is needed
# ---------------------------------------------------------------------------

def _mr(zone, match=None, score=0.9, name="test", neighbours=None):
    mr = MagicMock()
    mr.zone = zone
    mr.match = match
    mr.score = score
    mr.name = name
    mr.neighbours = neighbours or []
    return mr


class TestNormaliseIngredient:
    def test_confident_match_returns_canonical(self):
        with patch("kitchen_core.normalise.get_index") as mock_gi:
            mock_gi.return_value.find.return_value = _mr("confident", match="fish sauce", name="tiparos fish sauce")
            assert normalise_ingredient("tiparos fish sauce") == "fish sauce"

    def test_new_zone_returns_name_as_is(self):
        with patch("kitchen_core.normalise.get_index") as mock_gi:
            mock_gi.return_value.find.return_value = _mr("new", name="dragon fruit powder")
            assert normalise_ingredient("dragon fruit powder") == "dragon fruit powder"

    def test_grey_zone_llm_confirms_merge(self):
        neighbours = [("fish sauce", 0.81)]
        llm_resp = MagicMock()
        llm_resp.content = [MagicMock(text='{"match_index": 1, "canonical": "fish sauce"}')]
        with patch("kitchen_core.normalise.get_index") as mock_gi, \
             patch("kitchen_core.normalise.sync_client") as mock_sync:
            mock_gi.return_value.find.return_value = _mr("grey", name="fish sauce extra", neighbours=neighbours)
            mock_sync.messages.create.return_value = llm_resp
            assert normalise_ingredient("fish sauce extra") == "fish sauce"

    def test_grey_zone_llm_declines_returns_original(self):
        llm_resp = MagicMock()
        llm_resp.content = [MagicMock(text='{"match_index": null, "canonical": null}')]
        with patch("kitchen_core.normalise.get_index") as mock_gi, \
             patch("kitchen_core.normalise.sync_client") as mock_sync:
            mock_gi.return_value.find.return_value = _mr("grey", name="oyster soup", neighbours=[("fish sauce", 0.77)])
            mock_sync.messages.create.return_value = llm_resp
            assert normalise_ingredient("oyster soup") == "oyster soup"

    def test_lowercases_and_strips_input(self):
        with patch("kitchen_core.normalise.get_index") as mock_gi:
            mock_gi.return_value.find.return_value = _mr("confident", match="garlic", name="garlic")
            normalise_ingredient("  GARLIC  ")
            call_arg = mock_gi.return_value.find.call_args[0][0]
            assert call_arg == "garlic"


# ---------------------------------------------------------------------------
# normalise_batch_async — mock index + async LLM
# ---------------------------------------------------------------------------

class TestNormaliseBatchAsync:
    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        assert await normalise_batch_async([]) == []

    @pytest.mark.asyncio
    async def test_confident_items_resolved_without_llm(self):
        with patch("kitchen_core.normalise.get_index") as mock_gi, \
             patch("kitchen_core.normalise.async_client") as mock_async:
            mock_gi.return_value.find.return_value = _mr("confident", match="garlic", name="garlic")
            result = await normalise_batch_async(["garlic"])
            mock_async.messages.create.assert_not_called()
            assert result == ["garlic"]

    @pytest.mark.asyncio
    async def test_deduplicates_results(self):
        with patch("kitchen_core.normalise.get_index") as mock_gi:
            mock_gi.return_value.find.return_value = _mr("confident", match="garlic", name="garlic")
            result = await normalise_batch_async(["garlic", "Garlic"])
            assert result == ["garlic"]

    @pytest.mark.asyncio
    async def test_grey_items_resolved_via_llm(self):
        neighbours = [("fish sauce", 0.80)]
        llm_resp = MagicMock()
        llm_resp.content = [MagicMock(text='{"match_index": 1, "canonical": "fish sauce"}')]

        with patch("kitchen_core.normalise.get_index") as mock_gi, \
             patch("kitchen_core.normalise.async_client") as mock_async:
            mock_gi.return_value.find.return_value = _mr("grey", name="fish sauce lite", neighbours=neighbours, score=0.80)

            async def fake_create(**kwargs):
                return llm_resp
            mock_async.messages.create = fake_create

            result = await normalise_batch_async(["fish sauce lite"])
            assert result == ["fish sauce"]
