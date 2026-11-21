PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: setup models check-ollama seed run test eval lint clean-storage

setup:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -r requirements.txt -r requirements-dev.txt
	@test -f .env || cp .env.example .env
	@echo "Done. Set RXD_JWT_SECRET in .env to a long random string."

models:
	ollama pull qwen2.5:1.5b
	ollama pull nomic-embed-text

check-ollama:
	$(BIN)/python scripts/check_ollama.py

seed:
	$(BIN)/python scripts/seed.py

run:
	$(BIN)/uvicorn app.main:app --reload

test:
	$(BIN)/python -m pytest

eval:
	$(BIN)/python scripts/evaluate.py

lint:
	$(BIN)/ruff check app scripts tests

clean-storage:
	rm -rf storage
