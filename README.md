# Aries News

Search real-time news, generate an AI **summary + sentiment** for any article on
demand, store the results, and browse them on an **AI Insights** page.

Built as an async, all-Python app: **FastAPI + HTMX + PostgreSQL**, with OpenAI
(`gpt-4.1-nano`) for the analysis and [gnews.io](https://gnews.io) for headlines.
The UI is server-rendered (Jinja2 + HTMX + Alpine.js) with a hand-authored, flat
**Bauhaus-inspired** design in **light and dark** themes — muted primaries and
geometric shapes, with sentiment shown as a spectrum bar and a colour-sampled
accent.

- **Live demo:** <https://aries-news.onrender.com>
  _(free tier — the first request may cold-start for ~30s)_
- **How it works (diagrams, data model, failure modes):**
  [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **Why this stack:** [`docs/adr/0001-stack-and-async.md`](docs/adr/0001-stack-and-async.md)
- **Build status & roadmap:** [`PROGRESS.md`](PROGRESS.md)
- **Contributing / agent guide:** [`AGENTS.md`](AGENTS.md)

## Design focus

The case study called out three focus areas. Where we landed on each (full
rationale in [ADR-0001](docs/adr/0001-stack-and-async.md) and
[`ARCHITECTURE.md`](ARCHITECTURE.md)):

### Product design & UX

- **Server-rendered, tiny-JS stack** (Jinja2 + HTMX + Alpine) — hand-extendable
  with no build step or second toolchain.
- **Non-blocking analysis:** _Analyze_ returns a pending card instantly and an
  SSE stream swaps in the result, so you keep browsing while the AI works.
- **Idempotent, forgiving actions:** re-analyzing returns the existing insight;
  a failed analysis auto-retries on re-request.
- **Server-side view toggle (cards/list) and sort;** generated summaries persist
  across re-search/re-sort, matched by normalized URL.
- **AI Insights page** with a sentiment spectrum bar, a score-sampled halo, and a
  client-side sentiment filter; Bauhaus light/dark theme.

### REST API design

- **One-directional layering:** `api/ → services/ → repositories/ → models/ +
  schemas/`.
- **Two HTTP surfaces** (JSON API + HTML page routes) share one service layer.
- **Resource-oriented insights API** with honest status codes: `POST` → **202**
  (idempotent), `GET` list/detail (**404** when absent), `GET …/stream` (SSE);
  upstream news failure → **502**.
- **Pydantic contracts at every boundary** (`response_model`-enforced);
  idempotency enforced in the schema (unique `url_normalized`).

### AI features

- **Structured outputs** (`chat.completions.parse` with a Pydantic
  `response_format`) guarantee the shape — no defensive parsing.
- **One call** yields a neutral summary, a sentiment label, and a continuous
  score in `[-1, 1]` kept consistent with the label; the score drives the UI
  spectrum bar and halo.
- **Runs out-of-band** in a background job (slow + paid), bounded by a semaphore;
  transient-only retry with backoff, permanent failures mark the job failed.
- **Injectable OpenAI client,** so tests never hit the network.

## Prerequisites

- **Python 3.12**
- **[uv](https://docs.astral.sh/uv/)** — dependency & environment manager
- **Docker** — runs local PostgreSQL (the app itself runs on the host)
- API keys: a **gnews.io** key (free tier: 100 requests/day) and an **OpenAI**
  key

## Setup

```bash
# 1. Install runtime + dev dependencies and the Playwright browser
make install

# 2. Configure environment — copy the example and fill in your keys
cp .env.example .env
#    edit .env → set GNEWS_API_KEY and OPENAI_API_KEY
#    (DATABASE_URL already matches the docker-compose Postgres defaults)

# 3. Start local Postgres
make db-up

# 4. Apply database migrations
make migrate
```

## Run

```bash
make run            # http://127.0.0.1:8000  (uvicorn, autoreload)
```

A liveness probe is available at `GET /health`. The news search JSON endpoint is
`GET /api/news/search?q=…`.

## Test & check

```bash
make test           # full unit/integration suite with coverage
make test-fast      # fast subset (no coverage, no e2e) — for pre-commit
make test-e2e       # Playwright browser smoke test
make check          # lint + typecheck + pylint + tests (CI also runs e2e)
```

Run `make help` for the full list of targets, and `make format` to auto-format.

The suite runs against an isolated `<db>_test` database (e.g. `aries_test`),
created automatically, so `make test` / `make check` never touch your dev data.

## Troubleshooting

**`asyncpg.exceptions.UndefinedTableError: relation "insights" does not exist`
on `make run`** (and `make migrate` prints no `Running upgrade` line) — your dev
schema and Alembic's version pointer have drifted: the `alembic_version` row says
you're migrated, but the tables are gone. Rebuild the schema from scratch:

```bash
make db-reset       # drops the schema (DELETES ALL LOCAL DATA), re-runs migrations
```

This most often happened when the test suite dropped the app's tables; the suite
is now isolated to a separate `<db>_test` database, so it no longer occurs.

## Deploy

The app ships as a Docker image and runs its migrations on start. The repo
includes a [Render Blueprint](render.yaml) for a one-click deploy:

1. On [Render](https://dashboard.render.com), choose **New + → Blueprint** and
   connect this repo.
2. Render builds the Dockerfile, provisions PostgreSQL, wires `DATABASE_URL`,
   and runs migrations automatically.
3. Set `GNEWS_API_KEY` and `OPENAI_API_KEY` when prompted.

Any Dockerfile-based host works (Railway, Fly.io, …) — set the same env vars.
Run a **single web instance**: the worker and SSE are in-process (see
[ADR-0001](docs/adr/0001-stack-and-async.md)). A platform-provided
`postgres://` URL is coerced to the async driver automatically.

## Project layout

```text
src/app/
  main.py        FastAPI app factory
  core/          config, async DB engine, enums, URL normalization
  models/        SQLAlchemy tables — Article, Insight
  schemas/       Pydantic contracts (API + provider boundaries)
  repositories/  database access layer
  services/      news (gnews) + insights (OpenAI + background JobQueue)
  api/           HTTP routers — JSON, HTMX pages, SSE
  migrations/    Alembic env + versioned migrations
tests/           pytest (+ pytest-httpx, hypothesis, Playwright)
design/mockups/  early UI design explorations
docs/adr/        architecture decision records
```

Quality gates: `ruff` (format + lint, google docstrings), `pyright` (strict),
`pylint` (design), `pytest` (+ `hypothesis`, Playwright). See
[`AGENTS.md`](AGENTS.md) for conventions.

## Status

Complete and deployed — live at <https://aries-news.onrender.com>, with CI green
on `main`. See [`PROGRESS.md`](PROGRESS.md) for the full checklist.
