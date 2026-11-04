# Plano de trabalho

Cada fase termina com um commit (ou vários), com testes a passar.

## Fase 0 — Investigação e proposta
- [x] Confirmar endpoints e esquema reais (ver [API.md](API.md))
- [x] Propor a stack e a arquitetura (README)

## Fase 1 — Esqueleto
- [x] `pyproject.toml` (uv), `ruff`, `pytest`, `Makefile`
- [x] `docker-compose.yml`: Redpanda, TimescaleDB, coletor, processador, API web
- [x] Configuração por variáveis de ambiente (`pydantic-settings`)

## Fase 2 — Coletor
- [x] Polling de `/v2/vehicles` a cada 5 s (`httpx` async)
- [x] Normalização (unidade do timestamp, nulos, validação de coordenadas)
- [x] Deduplicação na origem: só se emite um evento quando `(id, timestamp)` muda
- [x] Produção para o tópico `vehicle-positions`, com chave = `vehicle_id` (garante ordem por veículo)
- [x] Falhas: timeout, *retry* com *backoff* exponencial e *jitter*, *circuit breaker*, métricas de "API em baixo"
- [x] Modo *record*: grava também em NDJSON, para *replay* em testes e demos

## Fase 3 — Persistência
- [x] Consumidor → TimescaleDB (`vehicle_positions` como hypertable)
- [x] Idempotência: `UNIQUE (vehicle_id, ts)` + `ON CONFLICT DO NOTHING`
- [x] Inserção em lote com *commit* do offset só depois do *commit* na BD (*at-least-once* + idempotência ⇒ efetivamente *exactly-once*)

## Fase 4 — GTFS e cálculo de atrasos
- [x] Carregar o ZIP de `/v2/gtfs` (trips, stop_times, calendar_dates, stops) para tabelas
- [x] Deteção de chegada à paragem: transição de `stop_id` / `STOPPED_AT`, com *geofence* (≤ 40 m) como reforço
- [x] `delay_s = observed_arrival − scheduled_arrival`, resolvendo horas GTFS > 24:00 e o dia de serviço
- [x] Eventos fora de ordem: *watermark* por veículo com tolerância configurável; eventos tardios são descartados e contados (`cm_late_events_total`)
- [x] Validação contra `/v2/arrivals/by_stop/:id` (`cmlive validate`), por correr com a API ao vivo

## Fase 5 — Agregações incrementais
- [x] *Continuous aggregates* do TimescaleDB: atraso por linha × hora, com atualização incremental
- [x] Vistas por dia da semana × hora (*heatmap*) e percentis p50/p90
- [x] Exportação para DuckDB/Parquet, para análise offline

## Fase 6 — Mapa ao vivo e dashboard
- [x] FastAPI: `GET /api/vehicles` (snapshot) + `GET /api/stream` (SSE)
- [x] Mapa com MapLibre GL, interpolação suave entre posições e cor pelo atraso
- [x] Página de análises (atraso por linha, *heatmap* hora × dia)

## Fase 7 — Observabilidade, testes e README final
- [x] Latência ponta a ponta instrumentada (`ts_veículo → ts_coletor → ts_kafka → ts_bd → ts_browser`)
- [ ] Medir volume e latência com a API ao vivo
- [x] Testes: unitários, propriedades (duplicados/ordem) e integração com `docker compose`
- [ ] README com capturas de ecrã e números medidos
