#!/usr/bin/env bash
# dev.sh — one-command local setup and run for Kitchen Agent
#
# Usage:
#   ./dev.sh          # install deps + start uvicorn + vite concurrently
#   ./dev.sh test     # install deps + run pytest + eslint + ruff (CI mode)
#
# Requirements: Python 3.12+, Node 20+
# Optional: set MOCK_CLAUDE=1 in .env to run without an Anthropic API key

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
VENV_DIR="$REPO_ROOT/.venv"

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
CYN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYN}[dev.sh]${NC} $*"; }
ok()   { echo -e "${GRN}[dev.sh]${NC} $*"; }
warn() { echo -e "${YLW}[dev.sh]${NC} $*"; }
err()  { echo -e "${RED}[dev.sh]${NC} $*" >&2; }

# ── Python venv ───────────────────────────────────────────────────────────────
setup_python() {
    if [ ! -d "$VENV_DIR" ]; then
        log "Creating Python virtual environment at .venv ..."
        python3 -m venv "$VENV_DIR"
    fi

    # Activate in this shell process
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    log "Installing Python package (pip install -e .[dev]) ..."
    pip install --quiet --upgrade pip
    pip install --quiet -e "$REPO_ROOT[dev]"
    ok "Python deps ready."
}

# ── Node / npm ────────────────────────────────────────────────────────────────
setup_node() {
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        log "Running npm install in frontend/ ..."
        (cd "$FRONTEND_DIR" && npm install --silent)
        ok "Node deps ready."
    else
        log "node_modules present — skipping npm install (run 'npm install' manually to update)."
    fi
}

# ── .env check ────────────────────────────────────────────────────────────────
check_env() {
    if [ ! -f "$REPO_ROOT/.env" ]; then
        warn ".env not found — copying from .env.example"
        cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
        warn "Edit .env and set DATABASE_URL (and optionally MOCK_CLAUDE=1), then re-run."
    fi
}

# ── Test mode ─────────────────────────────────────────────────────────────────
run_tests() {
    setup_python
    setup_node

    local failed=0

    # 1. pytest
    log "Running pytest tests/ ..."
    if pytest "$REPO_ROOT/tests/" -v; then
        ok "pytest: PASSED"
    else
        err "pytest: FAILED"
        failed=1
    fi

    # 2. Frontend lint (eslint) — only if script is present in package.json
    if (cd "$FRONTEND_DIR" && node -e "require('./package.json').scripts.lint" 2>/dev/null); then
        log "Running eslint (cd frontend && npm run lint) ..."
        if (cd "$FRONTEND_DIR" && npm run lint); then
            ok "eslint: PASSED"
        else
            err "eslint: FAILED"
            failed=1
        fi
    else
        warn "No 'lint' script in frontend/package.json — skipping eslint."
    fi

    # 3. ruff
    log "Running ruff check src/ api/ tools/ ..."
    local ruff_targets=()
    for d in src api tools; do
        [ -d "$REPO_ROOT/$d" ] && ruff_targets+=("$REPO_ROOT/$d")
    done
    if ruff check "${ruff_targets[@]}"; then
        ok "ruff: PASSED"
    else
        err "ruff: FAILED"
        failed=1
    fi

    if [ "$failed" -eq 0 ]; then
        ok "All checks passed."
    else
        err "One or more checks failed."
        exit 1
    fi
}

# ── Server mode ───────────────────────────────────────────────────────────────
run_servers() {
    check_env
    setup_python
    setup_node

    # Default the API URL for local dev so Vite always knows where the backend is
    export VITE_API_URL="${VITE_API_URL:-http://localhost:8000}"

    log "Starting uvicorn on :8000 and vite on :5173 ..."
    log "Press Ctrl+C to stop both."

    # Track child PIDs so we can kill them cleanly on exit
    UVICORN_PID=""
    VITE_PID=""

    cleanup() {
        echo ""
        log "Shutting down ..."
        [ -n "$UVICORN_PID" ] && kill "$UVICORN_PID" 2>/dev/null || true
        [ -n "$VITE_PID"    ] && kill "$VITE_PID"    2>/dev/null || true
        wait 2>/dev/null || true
        ok "All processes stopped."
    }
    trap cleanup INT TERM

    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    # Start uvicorn (reload for local dev — same binary Railway will run in prod)
    uvicorn api.main:app --reload --port 8000 --host 0.0.0.0 &
    UVICORN_PID=$!

    # Start vite
    (cd "$FRONTEND_DIR" && npm run dev) &
    VITE_PID=$!

    # Wait for either to exit (if one crashes we exit and cleanup fires)
    wait -n 2>/dev/null || wait
    cleanup
}

# ── Entry point ───────────────────────────────────────────────────────────────
case "${1:-}" in
    test)
        run_tests
        ;;
    "")
        run_servers
        ;;
    *)
        err "Unknown subcommand: $1"
        echo "Usage: $0 [test]"
        exit 1
        ;;
esac
