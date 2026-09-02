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

# Minimum EXECUTED-test floors enforced by tools/pytest_gate.py (Task 2B, C1).
# A suite that collects but skips everything, or points at a missing path, is
# RED no matter what pytest's exit code says. Floors are calibrated to the
# committed suites; RAISE them when adding tests, never lower them to get a
# green build — that is the failure this gate exists to make impossible.
# (Provisional values are finalised in todo 15 calibration against the real
# committed suite counts; see the Task 2B report.)
UNIT_MIN_EXECUTED ?= 99
INTEGRATION_MIN_EXECUTED ?= 30
SECURITY_MIN_EXECUTED ?= 109
UV    ?= uv
COMPOSE ?= docker compose

.PHONY: help dev down logs ps migrate migrate-new seed \
        lint format typecheck test test-property test-integration test-security \
        invariants brand api-types web-install web-build web-lint web-lint-clean \
        check ci clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Infrastructure -------------------------------------------------------

dev: ## Bring up PostgreSQL 18 + Redis 7 + MinIO + OTEL collector
	@# Requires a Docker runtime. NOT runnable in the authoring sandbox; that
	@# is expected and does not change the architecture. Verified by the
	@# compose-up job in CI. NO substitutions are made anywhere for these
	@# services — see docker-compose.yml and docs/ADR/0001.
	@#
	@# --wait is scoped to the services that declare a healthcheck. `docker
	@# compose up --wait` fails on any service without one, and otel-collector
	@# cannot have one: the image is distroless, so there is no shell for a
	@# container-internal probe. Confirmed by a real CI run — see ADR entry 10.
	$(COMPOSE) up -d --wait --wait-timeout 300 postgres redis minio
	$(COMPOSE) up -d otel-collector minio-init
	@echo "infrastructure up. next: make migrate"
	@echo "otel collector health: curl -fsS http://127.0.0.1:13133/"

down: ## Stop services, keep volumes
	$(COMPOSE) down

logs:
	$(COMPOSE) logs --no-log-prefix --tail=100

ps:
	$(COMPOSE) ps

# --- Database -------------------------------------------------------------

migrate: ## Apply migrations (forward-only, as the migrator role)
	@# check_rls_coverage runs BEFORE upgrade head, not after: a coverage gap
	@# (a tenant table with no policy file, or a policy file never wired into
	@# 0002's _POLICY_FILES) is a reason not to migrate at all, not a thing to
	@# discover once the schema is already live. See tools/check_rls_coverage.py.
	$(UV) run python tools/check_rls_coverage.py
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

test: ## Unit + property tests (no Docker required; gated on executed count)
	$(UV) run python tools/pytest_gate.py tests/unit --min-executed $(UNIT_MIN_EXECUTED) -- -q

test-property:
	$(UV) run pytest -m property -q

test-integration: ## Real PostgreSQL integration — REQUIRES DOCKER (gated)
	# Four-outcome gate: only genuinely-passing with >= floor EXECUTED tests is
	# green. Catches the three vacuous greens: missing path (exit 4), nothing
	# collected (exit 5), everything skipped (exit 0, ADR 0001 entry 9).
	$(UV) run python tools/pytest_gate.py tests/integration --min-executed $(INTEGRATION_MIN_EXECUTED) -- -q

test-security: ## Adversarial corpus: SSRF, injection, tenant isolation, XSS (gated)
	$(UV) run python tools/pytest_gate.py tests/security tests/unit/test_ssrf.py tests/unit/test_taint.py --min-executed $(SECURITY_MIN_EXECUTED) -- -q

invariants: ## ARCHITECTURE §6 invariants + brand-token drift
	$(UV) run python tools/check_zone_imports.py
	$(UV) run python tools/check_rls_coverage.py
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

web-lint: ## eslint + tsc (builds first — see below)
	@# `npm run build` BEFORE typecheck, matching the CI job order. Next.js
	@# generates global route types (LayoutProps, PageProps, the route union)
	@# into .next/types/ during the build, and app/layout.tsx depends on them.
	@# Typechecking first passes only when a PREVIOUS build left .next/types/
	@# on disk — which is how this repo reported green locally while CI failed
	@# with TS2304 on a fresh checkout. See ADR entry 11.
	cd apps/web && npm run lint && npm run build && npm run typecheck

web-lint-clean: ## web-lint from a pristine tree (catches stale-state false passes)
	@# Reproduces what CI actually sees. Use this before claiming apps/web is
	@# green; plain `web-lint` can inherit generated state from earlier runs.
	rm -rf apps/web/.next apps/web/tsconfig.tsbuildinfo
	$(MAKE) web-lint

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
