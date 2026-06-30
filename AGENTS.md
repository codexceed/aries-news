# Contributor & agent guide

Context for anyone — human or AI — working in this repo. It is intentionally
**disjoint** from the other docs: it points to them rather than repeating them.

- **What & how to run it:** [`README.md`](README.md)
- **How it's built (diagrams, data model, failure modes):**
  [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **Why the stack & async design were chosen:**
  [`docs/adr/`](docs/adr/) — start with
  [`0001-stack-and-async.md`](docs/adr/0001-stack-and-async.md)
- **What's done vs pending (the roadmap):** [`PROGRESS.md`](PROGRESS.md)

> **Resuming roadmap work?** Read [`PROGRESS.md`](PROGRESS.md) first, and
> **update its checkboxes** as you complete sub-items. It is the single source of
> truth for build state — keep it honest.

## Non-negotiables

- **Strict static typing.** `pyright` runs in `strict` mode; code must pass with
  zero errors. Full annotations on public functions (ruff `ANN`). `from
  __future__ import annotations` at the top of every module.
- **Google-style docstrings.** Enforced by ruff `D` (pydocstyle, google
  convention) and pylint's `docparams`. Public functions document `Args:`,
  `Returns:`, and `Raises:`.
- **Formatting & lint are not optional.** `ruff format` + `ruff check` own
  formatting, imports, naming, bugbear, async-correctness, simplify. `pylint`
  owns design smells (complexity, arg counts). Don't disable a rule to dodge it
  without a one-line reason in the config.
- **Testing rigor.** Unit tests for every service/pure function; mock upstreams
  (gnews via `pytest-httpx`, OpenAI) — never hit the network in tests. Use
  `hypothesis` for pure logic (URL normalization, sentiment parsing). Keep one
  meaningful Playwright smoke test, not a perf suite. Tests need not be
  docstring/annotation-strict (configured per-file).
- **ADRs for significant changes.** New architecture, a new feature's shape, or
  any public-interface change gets an ADR in [`docs/adr/`](docs/adr/) (copy the
  style of 0001). Reference it from the PR.
- **Be honest about limitations.** This project documents its failure modes
  rather than hiding them — preserve that. If you change the async/worker
  design, update both ARCHITECTURE.md §7 and ADR-0001.

## Where things live

The layering and full tree are in
[`ARCHITECTURE.md`](ARCHITECTURE.md#2-layering). In short:
`api/` → `services/` → `repositories/` → `models/` + `schemas/`, with
cross-cutting primitives in `core/`. Respect the one-directional dependency
flow: outer layers call inward, never the reverse. Keep SQL in `repositories/`,
business logic in `services/`, HTTP concerns in `api/`.

## Conventions that bite if missed

- **Migrations:** edit a model → `make makemigration m="…"` → review the
  generated revision (constraint/index names come from the convention in
  `core/db.py`; an autogenerate diff against the baseline should be empty).
  Never hand-edit applied history.
- **Config:** add settings to `core/config.Settings` (a pydantic-settings model);
  document the env var in `.env.example`. Read settings via `get_settings()`.
- **Idempotency:** article identity is `normalize_url()` (`core/url.py`) backed
  by a unique index — don't bypass it when inserting articles.
- **Enums** (`JobStatus`, `Sentiment`) are persisted Postgres enum types;
  changing a value is a migration, not just a code edit.

## Key commands

`make help` lists them all. Most-used:

| Command | What it does |
| --- | --- |
| `make install` | deps (uv) + Playwright chromium |
| `make db-up` / `make db-down` | local Postgres container |
| `make migrate` | apply migrations to head |
| `make makemigration m="…"` | autogenerate a revision |
| `make run` | uvicorn with autoreload |
| `make format` | ruff format + autofix |
| `make lint` / `make typecheck` / `make pylint` | individual gates |
| `make test` / `make test-fast` / `make test-e2e` | full / fast / Playwright |
| **`make check`** | **everything CI runs** — green before you push |

All Python runs inside the `uv` environment. **Run `make check` before
committing.**
