PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
ALEMBIC ?= $(PY) -m alembic

.PHONY: help venv install run test lint fmt upgrade-db downgrade-db clean compose-up compose-down smoke

help:
	@echo "make install      - install pinned deps into .venv"
	@echo "make run          - run the app with SQLite for local dev"
	@echo "make test         - run the test suite"
	@echo "make lint         - run ruff"
	@echo "make fmt          - run ruff --fix"
	@echo "make upgrade-db   - alembic upgrade head"
	@echo "make downgrade-db - alembic downgrade base"
	@echo "make compose-up   - docker compose up --build"
	@echo "make compose-down - docker compose down -v"
	@echo "make smoke        - run scripts/smoke_test.sh against http://localhost:8000"

venv:
	@if [ ! -d .venv ]; then python3.12 -m venv .venv; fi

install: venv
	$(PIP) install -r requirements.txt

run:
	$(PY) -m app.cli upgrade-db
	$(PY) -m uvicorn app.main:app --host 0.0.0.0 --port 8000

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check .

fmt:
	$(PY) -m ruff check --fix .

upgrade-db:
	$(PY) -m app.cli upgrade-db

downgrade-db:
	$(PY) -m app.cli downgrade-db

compose-up:
	docker compose up --build

compose-down:
	docker compose down -v

smoke:
	./scripts/smoke_test.sh http://localhost:8000

clean:
	rm -rf .pytest_cache .ruff_cache __pycache__ */__pycache__ */*/__pycache__
