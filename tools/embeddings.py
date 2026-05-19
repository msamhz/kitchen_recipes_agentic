"""
Embedding model for ingredient similarity.

Model: paraphrase-multilingual-MiniLM-L12-v2
  - 120MB, runs locally, no API calls
  - Handles English, Malay, Chinese, and 50+ other languages
  - 384-dimensional vectors

First run downloads the model to ~/.cache/huggingface/hub (automatic).
Subsequent runs load from cache instantly.
"""

import os
import ssl
import sys
import numpy as np

# Suppress tokenizer parallelism warning
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Bypass corporate SSL inspection.
# huggingface_hub uses httpx, so we must patch it before any HF import.
ssl._create_default_https_context = ssl._create_unverified_context
os.environ.setdefault("CURL_CA_BUNDLE", "")
os.environ.setdefault("REQUESTS_CA_BUNDLE", "")

import httpx
_orig_client_init = httpx.Client.__init__
def _ssl_bypass_client(self, *args, **kwargs):
    kwargs["verify"] = False
    _orig_client_init(self, *args, **kwargs)
httpx.Client.__init__ = _ssl_bypass_client

_orig_async_init = httpx.AsyncClient.__init__
def _ssl_bypass_async(self, *args, **kwargs):
    kwargs["verify"] = False
    _orig_async_init(self, *args, **kwargs)
httpx.AsyncClient.__init__ = _ssl_bypass_async

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print(f"[Embeddings] Loading model '{_MODEL_NAME}'...")
        _model = SentenceTransformer(_MODEL_NAME)
        print("[Embeddings] Model ready.")
    return _model


def encode(text: str) -> np.ndarray:
    """Encode a single string to a unit-normalised vector."""
    model = get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.astype(np.float32)


def encode_batch(texts: list[str]) -> np.ndarray:
    """Encode a list of strings, returns (N, 384) float32 array."""
    if not texts:
        return np.empty((0, 384), dtype=np.float32)
    model = get_model()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vecs.astype(np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two unit-normalised vectors (dot product suffices)."""
    return float(np.dot(a, b))


def top_matches(
    query_vec: np.ndarray,
    names: list[str],
    matrix: np.ndarray,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """
    Return top_k (name, score) pairs from matrix, sorted by similarity descending.
    matrix shape: (N, 384), query_vec shape: (384,)
    """
    if matrix.shape[0] == 0:
        return []
    scores = matrix @ query_vec  # (N,) dot products
    indices = np.argsort(scores)[::-1][:top_k]
    return [(names[i], float(scores[i])) for i in indices]


if __name__ == "__main__":
    # Smoke test
    print("Testing encode...")
    v1 = encode("fish sauce")
    v2 = encode("tiparos fish sauce")
    v3 = encode("bawang putih")
    v4 = encode("garlic")
    v5 = encode("chilli sauce")

    print(f"  'fish sauce' vs 'tiparos fish sauce': {cosine_similarity(v1, v2):.3f}")
    print(f"  'bawang putih' vs 'garlic':           {cosine_similarity(v3, v4):.3f}")
    print(f"  'fish sauce' vs 'chilli sauce':       {cosine_similarity(v1, v5):.3f}")
    print(f"  'fish sauce' vs 'bawang putih':       {cosine_similarity(v1, v3):.3f}")
