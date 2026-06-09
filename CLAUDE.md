# Agent Instructions

> **Operational source of truth:** `MASTER_PROMPT.md` governs how the agent team works (orchestration, block workflow, ownership lanes, roadmap). Where it overlaps with this file, `MASTER_PROMPT.md` wins. This file covers project facts, conventions, and the WAT philosophy.

You're working inside the **WAT framework** (Workflows, Agents, Tools). This architecture separates concerns so that probabilistic AI handles reasoning while deterministic code handles execution. That separation is what makes this system reliable.

## The WAT Architecture

**Layer 1: Workflows (The Instructions)**
- Markdown SOPs stored in `workflows/`
- Each workflow defines the objective, required inputs, which tools to use, expected outputs, and how to handle edge cases
- Written in plain language, the same way you'd brief someone on your team

**Layer 2: Agents (The Decision-Maker)**
- This is your role. You're responsible for intelligent coordination.
- Read the relevant workflow, run tools in the correct sequence, handle failures gracefully, and ask clarifying questions when needed
- You connect intent to execution without trying to do everything yourself
- Example: If you need to pull data from a website, don't attempt it directly. Read `workflows/scrape_website.md`, figure out the required inputs, then execute `tools/scrape_single_site.py`

**Layer 3: Tools (The Execution)**
- Python scripts in `tools/` that do the actual work
- API calls, data transformations, file operations, database queries
- Credentials and API keys are stored in `.env`
- These scripts are consistent, testable, and fast

**Why this matters:** When AI tries to handle every step directly, accuracy drops fast. If each step is 90% accurate, you're down to 59% success after just five steps. By offloading execution to deterministic scripts, you stay focused on orchestration and decision-making where you excel.

## How to Operate

**1. Look for existing tools first**
Before building anything new, check `tools/` based on what your workflow requires. Only create new scripts when nothing exists for that task.

**2. Learn and adapt when things fail**
When you hit an error:
- Read the full error message and trace
- Fix the script and retest (if it uses paid API calls or credits, check with me before running again)
- Document what you learned in the workflow (rate limits, timing quirks, unexpected behavior)
- Example: You get rate-limited on an API, so you dig into the docs, discover a batch endpoint, refactor the tool to use it, verify it works, then update the workflow so this never happens again

**3. Keep workflows current**
Workflows should evolve as you learn. When you find better methods, discover constraints, or encounter recurring issues, update the workflow. That said, don't create or overwrite workflows without asking unless I explicitly tell you to. These are your instructions and need to be preserved and refined, not tossed after one use.

## The Self-Improvement Loop

Every failure is a chance to make the system stronger:
1. Identify what broke
2. Fix the tool
3. Verify the fix works
4. Update the workflow with the new approach
5. Move on with a more robust system

This loop is how the framework improves over time.

## File Structure

**What goes where:**
- **Deliverables**: Final outputs go to cloud services (Google Sheets, Slides, etc.) where I can access them directly
- **Intermediates**: Temporary processing files that can be regenerated

**Directory layout:**
```
.tmp/           # Temporary files (scraped data, intermediate exports). Regenerated as needed.
tools/          # Python scripts for deterministic execution
workflows/      # Markdown SOPs defining what to do and how
.env            # API keys and environment variables (NEVER store secrets anywhere else)
credentials.json, token.json  # Google OAuth (gitignored)
```

**Core principle:** Local files are just for processing. Anything I need to see or use lives in cloud services. Everything in `.tmp/` is disposable.

## Project Reality (read this before assuming WAT-only)

The WAT framing above is the *philosophy*, but this project is a real product, not just `tools/` + `workflows/`. **Platform is migrating from AWS Lambda to Railway** (see `docs/platform-decision.md`); Neon and Vercel stay. Target shipped system:

```
Frontend (React PWA)          Backend (FastAPI on Railway)
Vercel (static hosting)  →→→  Railway container (uvicorn) → Neon Postgres (+pgvector)
```

- **Frontend:** Vite + React + Tailwind, deployed on Vercel (`frontend/`).
- **Backend:** FastAPI served by `uvicorn` in a container on **Railway** (`api/`). *(Currently still on Lambda + Mangum; migrates at block B4 — see `MASTER_PROMPT.md` §7. Mangum stays until Railway is verified.)*
- **Database:** Neon Postgres, everywhere (local + prod), with `pgvector` for RAG. SQLite is being retired.
- **AI:** Anthropic Claude (scan, parse, rate, recommend recipes).

**Target architecture:** a shared, env-agnostic Python package **`kitchen_core`** (pyproject `name = "kitchen-agent"`, `pip install -e .`) that both `api/` and local entrypoints import — eliminating today's duplication (e.g. `tools/normalise.py` vs `api/normalise.py`). The NiceGUI `app.py` is being **archived**; the React PWA is the UI going forward. The **same `uvicorn` process runs locally and on Railway** — no Mangum/API-Gateway layer once migrated. See `MASTER_PROMPT.md` §5 for the full plan.

## Repo Map

```
api/            FastAPI app (served by uvicorn on Railway; Mangum handler retired at B4); routes/
frontend/       React PWA (src/pages, src/components, src/api.js); Vercel + Edge middleware (Basic Auth)
kitchen_core/   Shared env-agnostic logic (PLANNED — normalise, embeddings, matching, shelf-life, etc.)
tools/          Legacy Python scripts (being folded into kitchen_core)
workflows/      Markdown SOPs (WAT)
.claude/agents/ Dev-team agents: senior-swe, frontend-react-engineer, qa-tester, readme-architect
.tmp/           Disposable temp files
.env            Secrets — never commit; mirror every new var into .env.example
```

## The Dev Team

Delegate to the right specialist (full briefs in `.claude/agents/`, workflow in `MASTER_PROMPT.md`):

- **senior-swe** — backend, `kitchen_core`, infra glue. Owns `kitchen_core/`, `api/`, `tools/`, `pyproject.toml`, `dev.sh`.
- **frontend-react-engineer** — UI/UX, FE state, perf; also **Lead Developer**. Owns `frontend/` only.
- **qa-tester** — writes **and runs** tests for every block.
- **readme-architect** — docs.

SWE and FE work **in parallel** on non-overlapping file sets. QA tests each block. Work proceeds in **blocks** (small shippable units with explicit goals); see `MASTER_PROMPT.md` §3.

## Commands

```
./dev.sh              # one-command local setup + run (venv + deps, npm install, uvicorn + vite)  [PLANNED]
./dev.sh test         # run pytest + vitest + lint  [PLANNED]
```
Backend deploy — **target:** git push to Railway (Dockerfile runs uvicorn). **Until B4 migration completes:** still Lambda (build image → ECR → `aws lambda update-function-code --function-name kitchen-agent --region ap-southeast-1`). Frontend: `vercel --prod`.

**Quality gate (must be green before deploy):** unit tests + lint + local build.

## Conventions

- Python **3.12**, Node **20**. Keep **Tailwind** (no new styling system without asking).
- **Git:** one feature branch per block (`feature/<name>`); commit + push when the Lead Developer is satisfied (don't wait for the owner); the owner reviews at the **PR** stage.
- **Secrets:** env vars only; every new variable must be added to `.env.example`.
- **Local-first:** every change must leave the zero-cloud local flow working (mock Claude + local DB).

## Non-Negotiables (do NOT change)

- **Neon** stays the database; keep DB and compute **co-located in the same region**.
- The live **Vercel URL** and its Edge **Basic Auth** middleware (frontend only repoints `VITE_API_URL`).
- No hardcoded secrets — env only.
- **Transition safety:** do not decommission Lambda until Railway is deployed and verified end-to-end.

> Superseded by the Railway migration: the old Lambda locks (function name `kitchen-agent`, API Gateway, the Mangum handler, pinned `ap-southeast-1`) are intentionally retired. See `MASTER_PROMPT.md` §6.

## Lessons & Gotchas (grow this as you learn)

- **Why we're leaving Lambda:** API Gateway caps requests at ~29s (raisable, but Lambda still maxes at 15 min), cold starts reload the embedding model every time, and streaming/cron are awkward. **Railway** (long-lived container) removes all of these — no request-timeout ceiling, warm model, native cron/SSE. Migrate at block B4; until then the 29s cap still applies, so don't ship a long synchronous endpoint on Lambda.
- **RAG lives in Neon via `pgvector`** — no separate vector DB needed; embeddings already exist (`embeddings.py`).
- **Zero-cloud local dev** requires mocking Claude so devs don't burn paid API credits.
- **Known duplication being removed:** `tools/normalise.py` vs `api/normalise.py`, and two DB layers — consolidate into `kitchen_core`.
- *(Append new gotchas here whenever a session discovers a constraint, rate limit, or surprising behaviour — this is step 4 of the Self-Improvement Loop.)*

## Bottom Line

You sit between what I want (workflows) and what actually gets done (tools). Your job is to read instructions, make smart decisions, call the right tools, recover from errors, and keep improving the system as you go.

Stay pragmatic. Stay reliable. Keep learning.
