export PYTHONPATH := src
PYTHON ?= /usr/local/bin/python3.12
VENV := .venv
BIN := $(VENV)/bin
# Company the demo opens with. Others stay selectable from the dev header.
COMPANY ?= $(shell ls companies | head -1)

.PHONY: setup lint test web-test gen-api eval demo

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"
	@# macOS can flag the editable .pth as hidden, which makes Python ignore it
	@chflags nohidden $(VENV)/lib/python3.12/site-packages/*.pth 2>/dev/null || true
	cd web && npm install && npx playwright install chromium

lint:
	$(BIN)/ruff check .

# Backend tests, lint, frontend unit tests, the browser smoke test, and the production build.
test: lint
	$(BIN)/pytest
	$(MAKE) web-test
	cd web && npm run build

# Vitest + React Testing Library, then one Playwright smoke test (submit a lead, see a booking).
web-test:
	cd web && npm test
	cd web && npm run e2e

# Re-export the OpenAPI schema and regenerate the typed web client from it.
gen-api:
	$(BIN)/python scripts/export_openapi.py
	cd web && npm run gen:api

# Runs every company's scenarios against the live model (needs ANTHROPIC_API_KEY in .env), prints
# a results table and metrics, and saves evals/results/<timestamp>.json. Fails on any guardrail
# violation or failed scenario. EVAL_ARGS="--no-judge --only hot_lead_books --repeat 3" to tune.
eval:
	$(BIN)/python -m leadagent.evals --all $(EVAL_ARGS)

# API on :8000 and the Vite dev server on :5173 (proxying /api). Ctrl-C stops both.
demo:
	@trap 'kill 0' INT TERM EXIT; \
	$(BIN)/python run.py --company $(COMPANY) & \
	(cd web && npm run dev -- --open) & \
	wait
