"""
Ingredient Embedding Index
---------------------------
Maintains an in-memory numpy matrix of all ingredient embeddings loaded
from kitchen.db. Provides fast cosine similarity search without any API calls.

Similarity thresholds:
  >= 0.85  confident match   → merge immediately, no LLM needed
  0.75-0.85 grey zone        → pass top candidates to LLM for confirmation
  <  0.75  no match          → genuinely new ingredient, add as-is

Usage:
    index = IngredientIndex()
    index.load()                         # load all embedded rows from DB
    result = index.find("tiparos fish sauce")
    # result.match = "fish sauce", result.score = 0.951, result.zone = "confident"
"""

import io
import os
import sys
from dataclasses import dataclass

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from db_init import get_connection
from embeddings import encode, encode_batch, top_matches

CONFIDENT = 0.85
GREY_LOW  = 0.70


@dataclass
class MatchResult:
    name: str           # input name (normalised lowercase)
    match: str | None   # canonical name from DB, or None
    score: float        # cosine similarity (0-1)
    zone: str           # "confident" | "grey" | "new"
    neighbours: list[tuple[str, float]]  # top-5 for grey zone LLM calls


class IngredientIndex:
    def __init__(self):
        self.names: list[str] = []
        self.matrix: np.ndarray = np.empty((0, 384), dtype=np.float32)

    # ------------------------------------------------------------------
    # Load / save to DB
    # ------------------------------------------------------------------

    def load(self):
        """Load all ingredients that already have embeddings from DB."""
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
        vecs = [_blob_to_vec(r["embedding"]) for r in rows]
        self.matrix = np.stack(vecs, axis=0).astype(np.float32)

    def add(self, name: str, vec: np.ndarray):
        """Add a new entry to the in-memory index (call after saving to DB)."""
        self.names.append(name)
        self.matrix = (
            np.vstack([self.matrix, vec[np.newaxis, :]])
            if self.matrix.shape[0] > 0
            else vec[np.newaxis, :].astype(np.float32)
        )

    def remove(self, name: str):
        """Remove an entry (used when an ingredient is deleted/merged)."""
        if name in self.names:
            idx = self.names.index(name)
            self.names.pop(idx)
            self.matrix = np.delete(self.matrix, idx, axis=0)

    # ------------------------------------------------------------------
    # Similarity search
    # ------------------------------------------------------------------

    def find(self, name: str) -> MatchResult:
        """
        Find the closest existing ingredient for a given name.
        Returns a MatchResult with zone = confident | grey | new.
        """
        name = name.strip().lower()

        # Exact match — skip embedding entirely
        if name in self.names:
            return MatchResult(name=name, match=name, score=1.0, zone="confident", neighbours=[])

        if self.matrix.shape[0] == 0:
            return MatchResult(name=name, match=None, score=0.0, zone="new", neighbours=[])

        vec = encode(name)
        neighbours = top_matches(vec, self.names, self.matrix, top_k=5)
        best_name, best_score = neighbours[0]

        if best_score >= CONFIDENT:
            zone = "confident"
            match = best_name
        elif best_score >= GREY_LOW:
            zone = "grey"
            match = None  # LLM will decide
        else:
            zone = "new"
            match = None

        return MatchResult(
            name=name,
            match=match,
            score=best_score,
            zone=zone,
            neighbours=neighbours,
        )

    # ------------------------------------------------------------------
    # DB persistence helpers
    # ------------------------------------------------------------------

    def embed_and_save(self, name: str) -> np.ndarray:
        """Encode name, persist embedding to DB, add to in-memory index."""
        vec = encode(name)
        _save_embedding(name, vec)
        self.add(name, vec)
        return vec

    def backfill(self, batch_size: int = 50):
        """Embed and save all ingredients in DB that have no embedding yet."""
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM ingredients WHERE embedding IS NULL")
        pending = [r["name"] for r in cur.fetchall()]
        conn.close()

        if not pending:
            print("[Index] All ingredients already embedded.")
            return

        print(f"[Index] Backfilling {len(pending)} ingredient(s)...")
        for i in range(0, len(pending), batch_size):
            chunk = pending[i : i + batch_size]
            vecs = encode_batch(chunk)
            conn = get_connection()
            cur = conn.cursor()
            for name, vec in zip(chunk, vecs):
                cur.execute(
                    "UPDATE ingredients SET embedding = ? WHERE name = ?",
                    (_vec_to_blob(vec), name),
                )
                self.add(name, vec)
            conn.commit()
            conn.close()
            print(f"[Index]   {min(i + batch_size, len(pending))}/{len(pending)}")

        print("[Index] Backfill complete.")


# ------------------------------------------------------------------
# Blob serialisation — store float32 vectors as raw bytes
# ------------------------------------------------------------------

def _vec_to_blob(vec: np.ndarray) -> bytes:
    return vec.astype(np.float32).tobytes()


def _blob_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _save_embedding(name: str, vec: np.ndarray):
    conn = get_connection()
    conn.execute(
        "UPDATE ingredients SET embedding = ? WHERE name = ?",
        (_vec_to_blob(vec), name),
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# Module-level singleton — shared across the app process
# ------------------------------------------------------------------

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


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from db_init import init_db
    init_db()

    idx = IngredientIndex()
    idx.backfill()

    print("\n--- Similarity tests ---")
    for query in ["tiparos fish sauce", "bawang putih", "egg", "miso paste", "kicap lemak manis"]:
        r = idx.find(query)
        print(f"  '{query}' -> match='{r.match}' score={r.score:.3f} zone={r.zone}")
