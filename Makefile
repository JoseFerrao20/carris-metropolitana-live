.PHONY: install test test-front test-all lint up-infra up down logs gtfs-local bench front

install:
	uv sync

test:
	uv run pytest

test-front: ## frontend: typecheck, lint, Vitest, build e Playwright
	cd frontend && npm ci && npm run typecheck && npm run lint && npm test && npm run build && npm run e2e

front: ## compila o frontend para src/cmlive/web/dist (servido pelo FastAPI)
	cd frontend && npm ci && npm run build

test-all: ## inclui os testes de integração (precisa de `make up-infra`)
	uv run pytest -m "" -v

lint:
	uv run ruff check . && uv run ruff format --check .

up-infra:
	docker compose up -d timescaledb redpanda topics

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f collector ingestor delay-engine

gtfs-local: ## carrega data/gtfs.zip em vez de descarregar
	CMLIVE_GTFS_ZIP=/data/gtfs.zip docker compose up gtfs

bench: ## volume e latência medidos (com o sistema a correr há algum tempo)
	curl -s localhost:8000/api/stats | python3 -m json.tool
