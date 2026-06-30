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

## Git & pull requests

`main` is protected: **no direct pushes** — land every change through a pull
request, and the **`quality` CI check must pass** before merge. History is
**linear**, so merge with **squash** or **rebase**, never a merge commit. (The
repo owner can bypass these for the occasional hotfix.)

- **Branch** off `main`: `git switch -c <type>/<short-topic>` (e.g.
  `feat/insights-filter`, `fix/url-normalization`).
- **Conventional Commits** for every commit message and the PR title:
  `type(scope): summary`, where `type` is one of `feat`, `fix`, `docs`,
  `refactor`, `test`, `ci`, `chore`, `perf`. These drive release-please's
  version bump + `CHANGELOG.md`.
- **`make check` green before you push.** The pre-commit hook runs ruff +
  pyright + the fast (no-DB) tests on commit; CI re-runs the full gate.
- **PR body** follows [`.github/pull_request_template.md`](.github/pull_request_template.md).
  Keep it **brief** — PRs are reference for human readers:
  - **Description** — one-line overview of the change.
  - **Motivation** — why it's needed.
  - **Changes** — bulleted list of what changed.
  - **Testing** — how it was verified.
- Reference an ADR when the change is architectural (see Non-negotiables).

### Explain a major change after opening its PR

For a **major change** (new architecture, a new feature's shape, or a
public-interface change — the same bar that warrants an ADR), don't just hand
over the PR link. Present the user a **brief, visually rich** summary in the
chat:

- **Architecture** — a small Mermaid (or ASCII) diagram of the components the
  change touches and how they relate.
- **Flow** — a sequence/flow diagram of the new runtime path (request → … →
  result).
- **Example** — one concrete walkthrough: sample input → what happens → output.

Keep it skimmable, not a wall of text. Then ask the user **2–4 short follow-up
questions** that check and deepen their understanding (trade-offs taken, edge
cases, "what would you want next?") — use the answers to surface gaps before the
change is merged.

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
| **`make check`** | lint + typecheck + pylint + tests (CI also runs the e2e smoke) — green before you push |

All Python runs inside the `uv` environment. **Run `make check` before
committing.**
