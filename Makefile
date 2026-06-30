# Aries News — common developer commands.
# Run `make help` for the list. All Python commands run inside the uv environment.

.DEFAULT_GOAL := help
.PHONY: help install db-up db-down migrate makemigration run format lint typecheck \
        pylint test test-fast test-e2e check clean

UV := uv
APP := app.main:app
HOST ?= 127.0.0.1
PORT ?= 8000

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime + dev dependencies and Playwright browsers
	$(UV) sync --extra dev
	$(UV) run playwright install chromium

db-up: ## Start the local Postgres container
	docker compose up -d db

db-down: ## Stop the local Postgres container
	docker compose down

migrate: ## Apply database migrations to the latest revision
	$(UV) run alembic upgrade head

makemigration: ## Autogenerate a migration: make makemigration m="message"
	$(UV) run alembic revision --autogenerate -m "$(m)"

run: ## Run the app with autoreload
	$(UV) run uvicorn $(APP) --reload --host $(HOST) --port $(PORT)

format: ## Auto-format the codebase
	$(UV) run ruff format src tests
	$(UV) run ruff check --fix src tests

lint: ## Lint (ruff) without modifying files
	$(UV) run ruff check src tests
	$(UV) run ruff format --check src tests

typecheck: ## Static type check (pyright, strict)
	$(UV) run pyright

pylint: ## Extra design/complexity checks (pylint)
	$(UV) run pylint src/app

test: ## Run the full unit/integration suite with coverage
	$(UV) run pytest --cov --cov-report=term-missing -m "not e2e"

test-fast: ## Fast subset for pre-commit (pure logic; no DB, no e2e)
	$(UV) run pytest -m "not e2e and not db" -x -q

test-e2e: ## Run the Playwright browser smoke test
	$(UV) run pytest -m e2e

check: lint typecheck pylint test ## Run everything CI runs

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dist build **/__pycache__
