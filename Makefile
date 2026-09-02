.DEFAULT_GOAL := help
CORE := apps/core
COMPOSE := docker compose -f infra/docker-compose.yml

.PHONY: help install lint fmt type test test-cov check up down logs psql migrate revision clean

help: ## Buyruqlar ro'yxati
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ── Ishlab chiqish ────────────────────────────────────────────────
install: ## Dependency'larni o'rnatish
	cd $(CORE) && uv sync --all-extras

lint: ## Ruff lint + format tekshiruvi
	cd $(CORE) && uv run ruff check src tests
	cd $(CORE) && uv run ruff format --check src tests

fmt: ## Kodni formatlash va avtomatik tuzatish
	cd $(CORE) && uv run ruff check --fix src tests
	cd $(CORE) && uv run ruff format src tests

type: ## mypy --strict
	cd $(CORE) && uv run mypy src

test: ## Testlar (unit)
	cd $(CORE) && uv run pytest -m "not integration and not live"

test-cov: ## Testlar + qamrov hisoboti
	cd $(CORE) && uv run pytest -m "not live" --cov=zet --cov-report=term-missing --cov-report=xml

check: lint type test ## Barcha sifat darvozalari

# ── Infratuzilma ──────────────────────────────────────────────────
up: ## Dev muhitini ko'tarish (Postgres + Redis)
	$(COMPOSE) up -d --wait

down: ## Dev muhitini to'xtatish
	$(COMPOSE) down

logs: ## Konteyner loglari
	$(COMPOSE) logs -f

psql: ## Postgres shell
	$(COMPOSE) exec postgres psql -U zet -d zet

# ── Migratsiya ────────────────────────────────────────────────────
migrate: ## Migratsiyalarni qo'llash
	cd $(CORE) && uv run alembic upgrade head

revision: ## Yangi migratsiya (make revision M="izoh")
	cd $(CORE) && uv run alembic revision --autogenerate -m "$(M)"

clean: ## Kesh fayllarni tozalash
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(CORE)/.pytest_cache $(CORE)/.mypy_cache $(CORE)/.ruff_cache $(CORE)/.coverage
