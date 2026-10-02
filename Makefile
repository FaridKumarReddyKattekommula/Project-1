# Detect the OS: Windows uses .venv\Scripts and `python`, Mac/Linux use .venv/bin and `python3`.
ifeq ($(OS),Windows_NT)
PYTHON ?= python
BIN    := .venv\Scripts
ACTIVATE := .venv\Scripts\activate
else
PYTHON ?= python3
BIN    := .venv/bin
ACTIVATE := source .venv/bin/activate
endif
VENV   := .venv
STAMP  := $(VENV)/.installed

.PHONY: install seed run test lint check docker clean

# Venv activation is per-shell, so each target calls the venv's tools directly
# (same effect as `source .venv/bin/activate` on Mac/Linux, `.venv\Scripts\activate` on Windows).
install: $(STAMP)
	@echo Done. To activate the venv in your terminal, run: $(ACTIVATE)
$(STAMP): pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install -q --upgrade pip
	$(BIN)/python -m pip install -q -e ".[dev]"
	$(BIN)/python -c "import pathlib; pathlib.Path('$(STAMP)').touch()"

seed: install
	$(BIN)/python -m app.db.seed --force

run: install
	$(BIN)/python -m uvicorn app.main:app --reload --port 8000

test: install
	$(BIN)/python -m pytest

lint: install
	$(BIN)/python -m ruff check app tests
	$(BIN)/python -m ruff format --check app tests
	$(BIN)/python -m mypy app

check: lint test

docker:
	docker build -t circle-recommendations .
	docker run --rm -p 8000:8000 circle-recommendations

clean:
	$(PYTHON) -c "import shutil; [shutil.rmtree(p, True) for p in ['.venv','var','.pytest_cache','.mypy_cache','.ruff_cache']]"
