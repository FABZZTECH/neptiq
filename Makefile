# NEPTIQ — Makefile
#
# THREE ENVIRONMENTS, different capabilities. Read docs/RUNBOOK.md.
#
#   authoring sandbox : no Docker. `check` runs; `dev` and `test-integration` cannot.
#   GitHub Actions    : AUTHORITATIVE GATE. Everything, including compose + testcontainers.
#   local machine     : interactive loop via `dev`.
#
# `check` is the complete set of things verifiable WITHOUT Docker. If `check`
# passes it means exactly that and nothing more — it does NOT mean `dev` works.

SHELL := /bin/bash
UV    ?= uv
COMPOSE ?= docker compose

.PHONY: help dev down logs ps migrate migrate-new seed \
        lint format typecheck test test-property test-integration test-security \
        invariants brand api-types web-install web-build web-lint check ci clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Infrastructure -------------------------------------------------------

dev: ## Bring up PostgreSQL 18 + Redis 7 + MinIO + OTEL collector
	@# Requires a Docker runtime. NOT runnable in the authoring sandbox; that
	@# is expected and does not change the architecture. Verified by the
	@# compose-up job in CI. NO substitutions are made anywhere for these
	@# services — see docker-compose.yml and docs/ADR/0001.
	$(COMPOSE) up -d --wait
	@echo "infrastructure up. next: make migrate"

down: ## Stop services, keep volumes
	$(COMPOSE) down

logs:
	$(COMPOSE) logs --no-log-prefix --tail=100

ps:
	$(COMPOSE) ps

# --- Database -------------------------------------------------------------

migrate: ## Apply migrations (forward-only, as the migrator role)
	$(UV) run alembic -c db/alembic.ini upgrade head

migrate-new: ## Create a revision: make migrate-new m="add x"
	$(UV) run alembic -c db/alembic.ini revision -m "$(m)"

# --- Static analysis and tests (all runnable without Docker) --------------

lint: ## ruff check + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

typecheck: ## mypy strict
	$(UV) run mypy packages apps/api tools

test: ## Unit + property tests (no Docker required)
	$(UV) run pytest tests/unit -q

test-property:
	$(UV) run pytest -m property -q

test-integration: ## Testcontainers integration — REQUIRES DOCKER
	$(UV) run pytest tests/integration -q

test-security: ## Adversarial corpus: SSRF, injection, tenant isolation, XSS
	$(UV) run pytest tests/security tests/unit/test_ssrf.py tests/unit/test_taint.py -q

invariants: ## ARCHITECTURE §6 invariants + brand-token drift
	$(UV) run python tools/check_zone_imports.py
	$(UV) run python tools/check_brand_tokens.py
	$(UV) run python tools/check_ci_drift.py

# --- Brand ----------------------------------------------------------------

brand: ## Rasterise brand assets from the SVG masters
	@bash scripts/build-brand.sh

# --- Frontend -------------------------------------------------------------

web-install:
	cd apps/web && npm ci

web-build: ## next build
	cd apps/web && npm run build

web-lint:
	cd apps/web && npm run lint && npm run typecheck

api-types: ## Regenerate apps/web/lib/api from the OpenAPI document
	@echo "generator lands with the first real API resource (see apps/web/lib/api/README.md)"

# --- Aggregates -----------------------------------------------------------

check: lint typecheck invariants test ## Everything verifiable WITHOUT Docker
	@echo ""
	@echo "PASSED: lint, mypy strict, §6 invariants, brand drift, unit + property tests."
	@echo "NOT verified here: docker compose up, integration/RLS tests, e2e."
	@echo "Those are gated by GitHub Actions. See docs/RUNBOOK.md."

ci: check test-integration test-security ## Full gate (CI only; needs Docker)

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache apps/web/.next
