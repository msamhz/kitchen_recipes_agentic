"""
Embedding model for ingredient similarity.

Model: paraphrase-multilingual-MiniLM-L12-v2
  - 120MB, runs locally, no API calls
  - Handles English, Malay, Chinese, and 50+ other languages
  - 384-dimensional vectors

First run downloads the model to ~/.cache/huggingface/hub.
"""

import os

import numpy as np

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print(f"[Embeddings] Loading model '{_MODEL_NAME}'...")
        try:
            _model = SentenceTransformer(_MODEL_NAME, backend="onnx")
            print("[Embeddings] Model ready (ONNX).")
        except Exception:
            _model = SentenceTransformer(_MODEL_NAME)
            print("[Embeddings] Model ready (PyTorch).")
    return _model


def encode(text: str) -> np.ndarray:
    """Encode a single string to a unit-normalised float32 vector."""
    vec = get_model().encode(text, normalize_embeddings=True)
    return vec.astype(np.float32)


def encode_batch(texts: list[str]) -> np.ndarray:
    """Encode a list of strings, returns (N, 384) float32 array."""
    if not texts:
        return np.empty((0, 384), dtype=np.float32)
    vecs = get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vecs.astype(np.float32)


async def encode_batch_async(texts: list[str]) -> np.ndarray:
    """Non-blocking version — runs encode_batch in a thread."""
    import asyncio
    return await asyncio.to_thread(encode_batch, texts)


def top_matches(
    query_vec: np.ndarray,
    names: list[str],
    matrix: np.ndarray,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """Return top_k (name, score) pairs sorted by cosine similarity descending."""
    if matrix.shape[0] == 0:
        return []
    scores = matrix @ query_vec
    indices = np.argsort(scores)[::-1][:top_k]
    return [(names[i], float(scores[i])) for i in indices]
