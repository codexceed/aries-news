# ADR 0002 — App-scoped services on `app.state`, injected via `Depends`

- **Status:** Accepted
- **Date:** 2026-07-01
- **Deciders:** Aries engineering case-study build

## Context

`NewsService` and `InsightsService` are process-wide singletons: each holds
state that must be shared across requests — `NewsService` owns an
`httpx.AsyncClient` and a TTL cache; `InsightsService` wraps the shared
`JobQueue` whose per-insight subscriber registry backs the SSE stream. Creating
a fresh instance per request would leak connections, void the cache, and — worst
of all — subscribe SSE clients to a `JobQueue` the worker never publishes to.

Before this ADR the two services were exposed **inconsistently**:

- `NewsService` lived behind a lazy module-level singleton (`get_news_service()`
  + a `_ServiceHolder`), and was `Depends`-injected in the JSON API but called
  **directly** in the web routes.
- `InsightsService` was a bare module-level instance (`insights_service = …`),
  imported and called **directly** everywhere — never injected.

Two exposure styles, two lifetimes, and only one service had a clean test
override seam. We want one convention for both.

## Decision

**Store both services on `app.state`, create them in the lifespan, and resolve
them everywhere through shared `Depends` getters.**

- `main.py`'s lifespan constructs `app.state.news_service` and
  `app.state.insights_service` on startup and calls `NewsService.aclose()` on
  shutdown — construction and disposal are bound to the app lifetime, not to the
  first request.
- `dependencies.py` holds `get_news_service` / `get_insights_service`, each
  taking a `Request` and returning `request.app.state.<service>`. This is the
  FastAPI-documented pattern for lifespan-created objects.
- Every router — JSON API (`api/news.py`, `api/insights.py`) **and** server-
  rendered pages (`web/routes.py`) — injects via `Depends`. No router imports a
  service instance.
- The `JobQueue` is created on `app.state.job_queue` in the same lifespan, which
  starts its worker on boot and stops it on shutdown (the `start_workers` /
  `stop_workers` wrappers in `api/insights.py` are gone). The app-state
  `InsightsService` is constructed with **that same queue instance**
  (`InsightsService(queue=queue)`), so the worker publishes to, and SSE
  endpoints subscribe on, one identical `JobQueue`. `InsightsService` no longer
  falls back to a module global — the queue is a required constructor argument,
  making the shared-instance invariant explicit.

## Alternatives considered

| Option | Why considered | Why not (now) |
| --- | --- | --- |
| **Keep module-level singletons** (status quo) | Zero churn; works | Leaves the two services inconsistent, ties `NewsService` lifecycle to first-request lazy init, and gives `InsightsService` no override seam. The inconsistency was the thing to fix. |
| **`Depends` getters over module singletons** (no `app.state`) | Uniform injection without touching the lifespan | Object lifetime still isn't tied to the app; testing still leans on module globals; doesn't follow the FastAPI convention for lifespan-created resources. |
| **Getter takes `Request` inside `services/`** | Fewer files | Imports the web framework (`Request`) into the service layer, violating the one-directional layering in ARCHITECTURE §2. Getters belong in the presentation tier (`dependencies.py`). |
| **Leave `JobQueue` a module singleton** | Lower risk; it was already lifespan-managed | Leaves an inconsistency (services on `app.state`, queue as a global) and keeps the `InsightsService`→global coupling. We instead moved it onto `app.state` and made the queue a required `InsightsService` argument; the shared-instance invariant is preserved by constructing the service with the started queue in the lifespan. No `Depends(get_job_queue)` getter was added — no route consumes the raw queue; it is injected into `InsightsService` at construction. |

## Consequences

- **One convention.** Both services share the same lifetime (app lifespan) and
  the same access path (`Depends` getter → `app.state`).
- **Cleaner tests.** Overriding a service is uniformly
  `app.dependency_overrides[get_*_service]`; the bare test app in `conftest.py`
  sets `app.state.insights_service` directly to mirror the lifespan.
- **No lazy first-request construction.** Services exist before the first
  request and are disposed deterministically on shutdown.
- **Trade-off:** path operations that reach a service now depend on an active
  `app.state` (populated by the lifespan). Tests that build a bare `FastAPI()`
  must populate `app.state` or override the getter — a small, explicit cost.
