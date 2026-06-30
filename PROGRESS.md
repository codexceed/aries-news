# Progress

Live build roadmap for Aries News. **Continuously updated** — when you finish a
sub-item, tick its box; when you resume work, read this first. Phases mirror the
approved plan. Sequencing principle: **get a locally running app first**; all
infra/CI/deploy is deferred to the end.

Legend: ✅ done · 🔄 in progress · ⏳ pending

---

## 1. Design sign-off ✅
- [x] Dusk Reading Room mockups (`design/mockups/dusk*.html`)
- [x] Tide mockups (`design/mockups/tide*.html`) for comparison
- [x] Direction chosen: **"Dusk + spectrum halo"** (`dusk-spectrum.html`) —
      warm dark reading-lamp theme, sentiment spectrum bar + sampled card halo
- [x] Palette + type locked (ink `#1B1E2B` / paper `#EDE6D6` / amber `#E8A24A`;
      sage→slate→clay sentiment gradient; Newsreader + Inter)

## 2. Project scaffold ✅
- [x] `pyproject.toml` — runtime + dev deps, ruff (format/lint + google
      docstrings), pyright strict, pylint (design), pytest config
- [x] `Makefile` — install/db/migrate/run/format/lint/typecheck/test/check
- [x] `.env.example` — DB, gnews, OpenAI, behavior knobs
- [x] `docker-compose.yml` — local Postgres only (app runs on host)
- [x] `alembic.ini` + async Alembic env

## 3. Backend core ✅
- [x] `core/config.py` — pydantic-settings `Settings` + cached singleton
      (coerces platform `postgres://` URLs to the async driver)
- [x] `core/db.py` — async engine, `AsyncSession` factory, `Base`, naming
      convention
- [x] `core/enums.py` — `JobStatus`, `Sentiment` (StrEnum)
- [x] `core/url.py` — `normalize_url` idempotency key
- [x] Models — `Article` (unique `url_normalized`), `Insight` (job state +
      result)
- [x] Schemas — `ArticleBase`/`ArticleRead`, `AnalysisResult`/`InsightRead`
- [x] Alembic baseline migration (`0001_baseline`, hand-authored)

## 4. News service ✅
- [x] `services/news.py` — httpx async client, tenacity retries (transient only)
- [x] Per-query in-memory TTL cache (protects the 100 req/day free tier)
- [x] gnews → `ArticleBase` mapping; drops articles without a usable URL
- [x] `api/news.py` — `GET /api/news/search` (validation, 502 on upstream fail)
- [x] Unit tests (`tests/test_news_service.py`, pytest-httpx) — 13 passing
- [x] Wired into `main.py`

## 5. Insights service (incl. JobQueue + SSE) ✅
- [x] OpenAI client — summary + structured sentiment → `AnalysisResult`
- [x] `repositories/insights.py` — article upsert, insight read/write, **job claim
      (`SELECT … FOR UPDATE SKIP LOCKED`)**, `get_with_article`/`list_all_with_articles`
- [x] `InsightsService` — URL-normalized idempotency (return existing on conflict)
- [x] `JobQueue` — asyncio worker loop, `asyncio.Semaphore` bound, `attempts`
- [x] **Startup reaper** — re-queue jobs stuck `running` past the stale timeout
- [x] `api/insights` — create/get/list endpoints + **SSE stream**
- [x] Lifespan wiring in `main.py` (worker start/stop, reaper on boot)
- [x] Unit tests written (mocked OpenAI green; DB-backed reaper/claim/idempotency
      ⏳ deferred until Postgres is up)

## 6. Frontend ✅
- [x] Jinja2 `base.html` + hand-authored design CSS (no runtime Tailwind/CDN)
- [x] Vendored htmx + htmx-sse + Alpine (local, fast, offline)
- [x] `core/sentiment.py` — pure marker%/gradient-sampled halo helper
- [x] Landing — search bar + nav (v2 prefetched-latest section stubbed in template)
- [x] Results page — server-side card/list toggle + sort, shimmer + **SSE swap**
- [x] AI Insights page — stored results, spectrum bar + halo, Alpine sentiment filter
- [x] HTMX wiring (analyze → pending fragment → SSE terminal swap)
- [x] Offline render check passes (all templates + halo/spectrum/sse invariants)
- [x] 🎯 **Milestone: app runs end-to-end locally (`make run`)** — verified

## 7. Tests ✅
- [x] News service unit tests (13)
- [x] OpenAI client unit tests (mocked, 4)
- [x] `hypothesis` property tests — URL normalization, sentiment, config coercion
- [x] `conftest.py` — test DB session + ASGI client fixtures; `db` auto-marker
- [x] Insights/JobQueue/reaper DB tests — passing against Postgres
- [x] **Playwright smoke** — landing + AI Insights card/halo/spectrum + filter
- [x] Full suite green: 39 unit/integration + 2 e2e; `make check` clean

## 8. Docs ✅
- [x] `ARCHITECTURE.md` — overview, flows, data model, state machine, SSE,
      failure modes
- [x] `docs/adr/0001-stack-and-async.md`
- [x] `AGENTS.md` + `CLAUDE.md` symlink
- [x] `PROGRESS.md` (this file)
- [x] `README.md` — full setup/run/test
- [ ] Final sweep once the app is verified end-to-end

## 9. Infra & deploy (LAST) 🔄
- [x] App `Dockerfile` + `.dockerignore` — image builds, migrates, and serves
- [x] `.pre-commit-config.yaml` — ruff + pyright + fast no-DB tests
- [x] `.github/workflows/ci.yml` — ruff + pyright + pylint + tests (Postgres) + e2e
      — **green on GitHub**
- [x] `.github/workflows/release.yml` — release-please
- [x] `render.yaml` — Render Blueprint (Docker web + managed Postgres)
- [x] Repo on GitHub — public: github.com/codexceed/aries-news
- [ ] Enable "Actions may create PRs" so release-please can open its release PR
- [ ] Deploy on Render → live link
- [x] Handover — public repo link (no invites needed)

---

### Current focus
Build complete and **green on CI** (ruff, pyright strict, pylint 10/10, 39
unit/integration tests + Playwright e2e). Two outstanding, both needing the repo
owner: (1) enable the Actions-create-PRs setting so the release workflow can run;
(2) connect the repo on Render (blueprint ready) with real `GNEWS_API_KEY` +
`OPENAI_API_KEY` for the live link.
