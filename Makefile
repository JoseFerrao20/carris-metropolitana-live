.PHONY: install test test-all lint up-infra up down logs gtfs-local bench

install:
	uv sync

test:
	uv run pytest

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
