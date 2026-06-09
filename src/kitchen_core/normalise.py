"""
Ingredient normalisation.

Strategy:
  >= 0.85  confident  — merge immediately, no LLM
  0.70–0.85 grey zone — one small Haiku call with top-3 neighbours
  < 0.70   new        — add as-is
"""

import asyncio
import json

from kitchen_core.clients import sync_client, async_client
from kitchen_core.ingredient_index import get_index

_GREY_PROMPT = """Kitchen ingredient deduplication. Singapore context.

New ingredient: "{name}"

Closest matches already in the database:
{neighbours}

Is the new ingredient the SAME physical ingredient as one of the above?
- Consider: brand variants, plurals, multilingual names (Malay/Chinese/English)
- Only say yes if HIGHLY confident — similar-sounding but different things should stay separate

Return ONLY valid JSON:
{{"match_index": 1, "canonical": "exact db name"}}
or if no match:
{{"match_index": null, "canonical": null}}
"""


def _fmt_neighbours(neighbours: list[tuple[str, float]]) -> str:
    return "\n".join(
        f'{i+1}. "{name}" (similarity: {score:.2f})'
        for i, (name, score) in enumerate(neighbours[:3])
    )


def _parse_grey(raw: str, neighbours: list[tuple[str, float]]) -> str | None:
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result = json.loads(raw.strip())
        canonical = (result.get("canonical") or "").strip().lower()
        if canonical and canonical in [n.lower() for n, _ in neighbours[:3]]:
            return canonical
    except Exception:
        pass
    return None


def normalise_ingredient(name: str) -> str:
    """Sync normalise for a single ingredient name."""
    name = name.strip().lower()
    index = get_index()
    result = index.find(name)

    if result.zone == "confident":
        return result.match

    if result.zone == "grey":
        resp = sync_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            messages=[{"role": "user", "content": _GREY_PROMPT.format(
                name=name,
                neighbours=_fmt_neighbours(result.neighbours),
            )}],
        )
        confirmed = _parse_grey(resp.content[0].text, result.neighbours)
        if confirmed:
            return confirmed

    return name


async def normalise_batch_async(names: list[str], log_fn=None) -> list[str]:
    """
    Async batch normalise.
    Confident + new resolved via vectors (no LLM).
    Grey zone items resolved in parallel with Haiku.
    Returns deduplicated list preserving original order.
    """
    if not names:
        return names

    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    index = get_index()
    results = [index.find(n.strip().lower()) for n in names]
    resolved: list[str] = [""] * len(names)
    grey_indices: list[int] = []

    for i, r in enumerate(results):
        if r.zone == "confident":
            resolved[i] = r.match
            _log(f"[Normalise] {r.name}  →  {r.match}  (score {r.score:.2f})")
        elif r.zone == "new":
            resolved[i] = r.name
            _log(f"[Normalise] {r.name}  —  new ingredient")
        else:
            grey_indices.append(i)
            _log(f"[Normalise] {r.name}  —  checking with AI (score {r.score:.2f})...")

    if grey_indices:
        tasks = [
            async_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=64,
                messages=[{"role": "user", "content": _GREY_PROMPT.format(
                    name=results[i].name,
                    neighbours=_fmt_neighbours(results[i].neighbours),
                )}],
            )
            for i in grey_indices
        ]
        responses = await asyncio.gather(*tasks)
        for resp, i in zip(responses, grey_indices):
            confirmed = _parse_grey(resp.content[0].text, results[i].neighbours)
            if confirmed:
                resolved[i] = confirmed
                _log(f"[Normalise] {results[i].name}  →  {confirmed}  (AI merged)")
            else:
                resolved[i] = results[i].name
                _log(f"[Normalise] {results[i].name}  —  AI kept as new")

    seen: list[str] = []
    for name in resolved:
        if name and name not in seen:
            seen.append(name)
    return seen
