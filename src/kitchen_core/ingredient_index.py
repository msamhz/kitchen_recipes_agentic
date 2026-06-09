"""
In-memory ingredient embedding index backed by Neon Postgres.

Similarity thresholds:
  >= 0.85  confident match  — merge immediately, no LLM
  0.70–0.85 grey zone       — one small Haiku call for confirmation
  <  0.70  new              — add as-is
"""

from dataclasses import dataclass, field

import numpy as np

from kitchen_core.db import get_connection
from kitchen_core.embeddings import encode, top_matches

CONFIDENT = 0.85
GREY_LOW = 0.70


@dataclass
class MatchResult:
    name: str
    match: str | None
    score: float
    zone: str  # "confident" | "grey" | "new"
    neighbours: list[tuple[str, float]] = field(default_factory=list)


class IngredientIndex:
    def __init__(self):
        self.names: list[str] = []
        self.matrix: np.ndarray = np.empty((0, 384), dtype=np.float32)

    def load(self):
        """Load all ingredients that have embeddings from Postgres."""
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, embedding FROM ingredients WHERE embedding IS NOT NULL")
        rows = cur.fetchall()
        conn.close()

        if not rows:
            self.names = []
            self.matrix = np.empty((0, 384), dtype=np.float32)
            return

        self.names = [r["name"] for r in rows]
        # psycopg2 returns BYTEA as memoryview; bytes() normalises both memoryview and bytes
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


# Module-level singleton — loaded once per process, persists across warm invocations
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
