# Aries News

Search real-time news, generate an AI **summary + sentiment** for any article on
demand, store the results, and browse them on an **AI Insights** page.

Built as an async, all-Python app: **FastAPI + HTMX + PostgreSQL**, with OpenAI
(`gpt-4.1-nano`) for the analysis and [gnews.io](https://gnews.io) for headlines.
The UI is server-rendered (Jinja2 + HTMX + Alpine.js + Tailwind) in a warm dark
"reading-lamp" theme, with sentiment shown as a spectrum bar and a colour-sampled
card halo.

- **How it works (diagrams, data model, failure modes):**
  [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **Why this stack:** [`docs/adr/0001-stack-and-async.md`](docs/adr/0001-stack-and-async.md)
- **Build status & roadmap:** [`PROGRESS.md`](PROGRESS.md)
- **Contributing / agent guide:** [`AGENTS.md`](AGENTS.md)

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
make check          # everything CI runs: lint + typecheck + pylint + test
```

Run `make help` for the full list of targets, and `make format` to auto-format.

## Project layout

```
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
design/mockups/  UI design explorations (chosen: dusk-spectrum.html)
docs/adr/        architecture decision records
```

Quality gates: `ruff` (format + lint, google docstrings), `pyright` (strict),
`pylint` (design), `pytest` (+ `hypothesis`, Playwright). See
[`AGENTS.md`](AGENTS.md) for conventions.

## Status

Backend core and the news service are in place; the insights service
(JobQueue + SSE) and the frontend are in progress. See
[`PROGRESS.md`](PROGRESS.md) for the up-to-date checklist.
