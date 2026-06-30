# ADR 0001 — Stack and async-job design

- **Status:** Accepted
- **Date:** 2026-06-30
- **Deciders:** Aries engineering case-study build

## Context

We are building a web app that searches real-time news, generates an AI
**summary + sentiment** for an article on user request, stores results in
PostgreSQL, and surfaces them on an **AI Insights** page. Analysis is a slow,
external, paid call (OpenAI), so it must run **out of band** from the request
that triggers it, and the UI must stay responsive while it runs.

A hard, unusual constraint shapes every choice: this same codebase hosts a
follow-up **no-AI live coding session**. The stack must be **hand-writable** —
small, all-Python, single deploy, minimal moving parts — not merely
feature-maximal. Expected scale is modest (a demo / small instance), and the
gnews free tier (100 req/day) must be respected.

## Decision

**Stack.** Python 3.12 · FastAPI (async-native) · PostgreSQL via SQLAlchemy 2.0
async + asyncpg · Alembic · Pydantic v2 / pydantic-settings · httpx · OpenAI SDK
(`gpt-4.1-nano`) · sse-starlette. **Frontend:** server-rendered Jinja2 + HTMX +
Alpine.js + Tailwind.

**Async jobs.** An **in-process `asyncio` worker** plus a DB-backed job row (the
`insights` table doubles as the job table), behind a swappable `JobQueue`
interface. Specifically:

- Workers claim the next `pending` job with `SELECT … FOR UPDATE SKIP LOCKED`
  and flip it to `running` in the same transaction — mutually exclusive pickup.
- An `asyncio.Semaphore` bounds concurrent OpenAI calls.
- A **startup reaper** re-queues jobs stuck `running` past a stale timeout.
- **Idempotency is in the schema:** a `UNIQUE` index on `articles.url_normalized`
  (and a unique `insights.article_id`) means one insight per article even under
  a race; a conflict returns the existing insight.
- The UI learns of completion over **SSE**, with polling as the fallback.

## Alternatives considered

| Option | Why considered | Why not (now) |
| --- | --- | --- |
| **arq + Redis** worker tier | Proper out-of-process jobs; Redis pub/sub solves cross-process SSE fan-out | Adds a broker + worker process + ops surface. Overkill at this scale and *harder to hand-write live*. **Designated v2 upgrade path** once we scale out. |
| **Celery (+ Redis/RabbitMQ)** | Mature, batteries-included task queue | Heaviest option; sync-first ergonomics clash with our async stack; most config to explain in a live session. |
| **React / Next.js frontend** | Richest interactivity | A second language/toolchain + build + separate deploy. Live-codeable only by JS specialists; defeats the all-Python goal. |
| **HTMX + Alpine + Jinja2 (chosen)** | Server-rendered, tiny JS surface, one deploy; HTMX partial swaps give "keep browsing while AI runs"; SSE extension for live updates | Less rich than a SPA — acceptable for this app. |
| **Threading / `BackgroundTasks` only** | No new deps | No durable state, no cross-restart recovery, no multi-worker safety. The DB-backed approach costs little more and buys all three. |

## Consequences

**Positive**
- One language, one process, one deploy — trivially hand-extensible in the live
  session.
- Durable, observable job state (plain SQL); self-healing on a single instance
  via the reaper.
- Safe under multiple web workers: the transactional claim prevents duplicate
  *work*; unique constraints prevent duplicate *insights*.
- Cost/rate control via the semaphore; gnews quota protected by a TTL cache.

**Negative / accepted limitations** (detailed in
[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md#7-failure-modes--limitations))
- **Jobs are tied to the app process** — no independent worker tier.
- **Deploy restarts can interrupt running jobs** — mitigated by DB state + reaper
  (cost is a redo, not a lost result).
- **SSE is per process** — breaks live-update *delivery* under horizontal scaling
  (work itself stays correct). The **arq + Redis pub/sub** path is the fix.
- A genuinely high-throughput or multi-instance future means revisiting this ADR
  in favour of the arq + Redis alternative above.

## Revisiting

Open a follow-up ADR when any of these hold: we need more than one app instance
for live updates, OpenAI throughput outgrows a single process, or jobs need
guaranteed isolation from web traffic. The expected move is **arq + Redis**.
