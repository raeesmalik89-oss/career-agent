.PHONY: install keys test test-pg e2e cov lint fmt migrate revision seed owner run up down logs prod-up smoke backup

export PYTHONPATH := backend:.

install:            ## install Python deps into .venv
	uv sync

keys:               ## print fresh JWT_SECRET / MASTER_KEY for .env
	uv run python -m app.cli gen-keys

test:               ## run tests on SQLite (no Docker needed)
	uv run pytest

test-pg:            ## run tests incl. PostgreSQL-only ones (needs `make up`)
	TEST_DATABASE_URL=postgresql+psycopg://career:career@localhost:5432/career_agent_test uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .

fmt:
	uv run ruff format . && uv run ruff check --fix .

migrate:            ## apply migrations to DATABASE_URL
	uv run alembic upgrade head

revision:           ## make revision m="message"
	uv run alembic revision --autogenerate -m "$(m)"

seed:
	uv run python -m app.cli seed

owner:              ## make owner email=you@example.com name="Your Name"
	uv run python -m app.cli create-owner --email "$(email)" --name "$(name)"

run:                ## dev server with reload
	uv run uvicorn app.main:app --reload --app-dir backend

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api scheduler web

e2e:                ## end-to-end journey test only
	uv run pytest tests/e2e

cov:                ## all tests with coverage (fails under the floor in pyproject.toml)
	uv run pytest --cov --cov-report=term

prod-up:            ## production on a server (needs DOMAIN and ACME_EMAIL in .env)
	docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build

smoke:              ## make smoke url=https://your-domain
	uv run python scripts/smoke.py "$(url)"

backup:             ## back up the local SQLite database now
	uv run python -m app.cli backup
