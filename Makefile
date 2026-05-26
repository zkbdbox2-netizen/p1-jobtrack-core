.PHONY: up down restart logs shell migrate migrate-create test lint

# Auto-detect: use "docker compose" (V2 plugin) if available, else fall back to
# "docker-compose" (V1 standalone). This makes the Makefile work on both.
COMPOSE := $(shell docker compose version > /dev/null 2>&1 && echo "docker compose" || echo "docker-compose")

# --- Development ---

up:
	$(COMPOSE) up --build

up-detached:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

down-volumes:
	$(COMPOSE) down -v   # WARNING: destroys the postgres volume (all data)

restart:
	$(COMPOSE) down && $(COMPOSE) up --build -d

logs:
	$(COMPOSE) logs -f app

shell:
	$(COMPOSE) exec app bash

# --- Database ---

migrate:
	# Apply all pending migrations
	$(COMPOSE) exec app alembic upgrade head

migrate-down:
	# Roll back one migration
	$(COMPOSE) exec app alembic downgrade -1

migrate-create:
	# Usage: make migrate-create name="add_jobs_table"
	$(COMPOSE) exec app alembic revision --autogenerate -m "$(name)"

migrate-history:
	$(COMPOSE) exec app alembic history --verbose

# --- Testing ---

test:
	$(COMPOSE) exec app pytest tests/ -v

test-cov:
	$(COMPOSE) exec app pytest tests/ -v --cov=app --cov-report=term-missing

# --- Health check ---

health:
	curl -s http://localhost:8000/health | python3 -m json.tool
