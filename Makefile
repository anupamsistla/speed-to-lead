PYTHON ?= /usr/local/bin/python3.12
VENV := .venv
BIN := $(VENV)/bin

.PHONY: setup test lint eval demo web-test

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"
	@if [ -f web/package.json ]; then cd web && npm install; fi

lint:
	$(BIN)/ruff check .

test: lint
	$(BIN)/pytest
	@if [ -f web/package.json ]; then cd web && npm test && npm run build; fi

eval:
	@echo "make eval arrives in phase 6" && exit 1

demo:
	@echo "make demo arrives in phase 5" && exit 1

web-test:
	@echo "make web-test arrives in phase 5" && exit 1
