# ── Stage 1: builder ────────────────────────────────────────────────────────
# Install Python deps in an isolated layer so they don't bloat the final image.
FROM python:3.12-slim AS builder

WORKDIR /build

# System libs required by psycopg2-binary, Pillow, and the ONNX runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the package manifest first so Docker can cache the pip layer.
COPY pyproject.toml ./
COPY src/ ./src/

# Install the package and all its deps into a prefix we'll copy forward.
RUN pip install --no-cache-dir --prefix=/install .


# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Same system libs needed at runtime (libpq for psycopg2, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Bring in the installed packages from the builder stage.
COPY --from=builder /install /usr/local

# Copy application source (api/ and src/ only — no frontend, no secrets).
COPY api/ ./api/
COPY src/ ./src/

# Create a non-root user and assign a writable home for the model cache.
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

# Pre-bake the ONNX embedding model as appuser so the cache directory
# (/home/appuser/.cache/huggingface/) is owned by the process that will
# load it at runtime.  This avoids a root-vs-appuser permission mismatch.
ENV HF_HOME=/home/appuser/.cache/huggingface
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2', backend='onnx')"

# Railway injects PORT at runtime; default to 8000 for local docker run.
ENV PORT=8000

EXPOSE ${PORT}

# uvicorn is the server — no API Gateway / Mangum layer needed here.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
