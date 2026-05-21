"""
Ingredient normalisation for the Postgres/Lambda API layer.

Direct port of tools/normalise.py + tools/ingredient_index.py but using the
Neon Postgres connection (api/db.py) instead of the local SQLite db_init.py.
SQL placeholders changed from ? to %s; embedding blob handled as bytes/memoryview.

Strategy (identical to tools/):
  >= 0.85  confident  — merge immediately, no LLM
  0.70–0.85 grey zone — one small Haiku call with top-3 neighbours
  < 0.70   new        — add as-is
"""

import asyncio
import json
from dataclasses import dataclass, field

import numpy as np

from api.db import get_connection
from tools.embeddings import encode, top_matches
from tools.clients import sync_client, async_client

CONFIDENT = 0.85
GREY_LOW  = 0.70

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


@dataclass
class MatchResult:
    name: str
    match: str | None
    score: float
    zone: str
    neighbours: list[tuple[str, float]] = field(default_factory=list)


class IngredientIndex:
    def __init__(self):
        self.names: list[str] = []
        self.matrix: np.ndarray = np.empty((0, 384), dtype=np.float32)

    def load(self):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, embedding FROM ingredients WHERE embedding IS NOT NULL")
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return
        self.names = [r["name"] for r in rows]
        vecs = [np.frombuffer(bytes(r["embedding"]), dtype=np.float32) for r in rows]
        self.matrix = np.stack(vecs).astype(np.float32)

    def add(self, name: str, vec: np.ndarray):
        self.names.append(name)
        self.matrix = (
            np.vstack([self.matrix, vec[np.newaxis, :]])
            if self.matrix.shape[0] > 0
            else vec[np.newaxis, :].astype(np.float32)
        )

    def remove(self, name: str):
        if name in self.names:
            idx = self.names.index(name)
            self.names.pop(idx)
            self.matrix = np.delete(self.matrix, idx, axis=0)

    def find(self, name: str) -> MatchResult:
        name = name.strip().lower()
        if name in self.names:
            return MatchResult(name=name, match=name, score=1.0, zone="confident")
        if self.matrix.shape[0] == 0:
            return MatchResult(name=name, match=None, score=0.0, zone="new")
        vec = encode(name)
        neighbours = top_matches(vec, self.names, self.matrix, top_k=5)
        best_name, best_score = neighbours[0]
        if best_score >= CONFIDENT:
            return MatchResult(name=name, match=best_name, score=best_score, zone="confident", neighbours=neighbours)
        if best_score >= GREY_LOW:
            return MatchResult(name=name, match=None, score=best_score, zone="grey", neighbours=neighbours)
        return MatchResult(name=name, match=None, score=best_score, zone="new", neighbours=neighbours)

    def embed_and_save(self, name: str) -> np.ndarray:
        """Compute embedding, persist to Postgres, add to in-memory index."""
        vec = encode(name)
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE ingredients SET embedding = %s WHERE name = %s", (vec.tobytes(), name))
        conn.commit()
        conn.close()
        self.add(name, vec)
        return vec


# Module-level singleton — loaded once per Lambda container, persists across warm invocations
_index: IngredientIndex | None = None


def get_index() -> IngredientIndex:
    global _index
    if _index is None:
        _index = IngredientIndex()
        _index.load()
    return _index


def reset_index():
    """Force reload on next get_index() call (e.g. after bulk merges)."""
    global _index
    _index = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _fmt_neighbours(neighbours: list[tuple[str, float]]) -> str:
    return "\n".join(
        f'{i+1}. "{name}" (similarity: {score:.2f})'
        for i, (name, score) in enumerate(neighbours[:3])
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalise_ingredient(name: str) -> str:
    """
    Sync normalise for a single ingredient name.
    Returns canonical name from DB if confident/grey match found, else name as-is.
    """
    name = name.strip().lower()
    index = get_index()
    result = index.find(name)

    if result.zone == "confident":
        return result.match

    if result.zone == "grey":
        resp = sync_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=64,
            messages=[{"role": "user", "content": _GREY_PROMPT.format(
                name=name, neighbours=_fmt_neighbours(result.neighbours),
            )}],
        )
        confirmed = _parse_grey(resp.content[0].text, result.neighbours)
        if confirmed:
            return confirmed

    return name


async def normalise_batch_async(names: list[str]) -> list[str]:
    """
    Async batch normalise. Confident + new resolved via vectors (no LLM).
    Grey zone items resolved in parallel with Haiku.
    Returns deduplicated list preserving original order.
    """
    if not names:
        return names

    index = get_index()
    results = [index.find(n.strip().lower()) for n in names]
    resolved: list[str] = [""] * len(names)
    grey_indices: list[int] = []

    for i, r in enumerate(results):
        if r.zone == "confident":
            resolved[i] = r.match
        elif r.zone == "new":
            resolved[i] = r.name
        else:
            grey_indices.append(i)

    if grey_indices:
        tasks = [
            async_client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=64,
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
            resolved[i] = confirmed if confirmed else results[i].name

    seen: list[str] = []
    for name in resolved:
        if name and name not in seen:
            seen.append(name)
    return seen
