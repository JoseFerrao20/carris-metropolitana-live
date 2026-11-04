# Plano de trabalho

Cada fase termina com um commit (ou vários), com testes a passar.

## Fase 0 — Investigação e proposta *(este commit)*
- [x] Confirmar endpoints e esquema reais (ver [API.md](API.md))
- [x] Propor a stack e a arquitetura (README)

## Fase 1 — Esqueleto
- [ ] `pyproject.toml` (uv), `ruff`, `pytest`, `Makefile`
- [ ] `docker-compose.yml`: Redpanda, TimescaleDB, coletor, processador, API web
- [ ] Configuração por variáveis de ambiente (`pydantic-settings`)

## Fase 2 — Coletor
- [ ] Polling de `/v2/vehicles` a cada 5 s (`httpx` async)
- [ ] Normalização (unidade do timestamp, nulos, validação de coordenadas)
- [ ] Deduplicação na origem: só se emite um evento quando `(id, timestamp)` muda
- [ ] Produção para o tópico `vehicle-positions`, com chave = `vehicle_id` (garante ordem por veículo)
- [ ] Falhas: timeout, *retry* com *backoff* exponencial e *jitter*, *circuit breaker*, métricas de "API em baixo"
- [ ] Modo *record*: grava também em NDJSON, para *replay* em testes e demos

## Fase 3 — Persistência
- [ ] Consumidor → TimescaleDB (`vehicle_positions` como hypertable)
- [ ] Idempotência: `UNIQUE (vehicle_id, ts)` + `ON CONFLICT DO NOTHING`
- [ ] Inserção em lote com *commit* do offset só depois do *commit* na BD (*at-least-once* + idempotência ⇒ efetivamente *exactly-once*)

## Fase 4 — GTFS e cálculo de atrasos
- [ ] Carregar o ZIP de `/v2/gtfs` (trips, stop_times, calendar_dates, stops) para tabelas
- [ ] Deteção de chegada à paragem: transição de `stop_id` / `STOPPED_AT`, com *geofence* (≤ 40 m) como reforço
- [ ] `delay_s = observed_arrival − scheduled_arrival`, resolvendo horas GTFS > 24:00 e o dia de serviço
- [ ] Eventos fora de ordem: *watermark* por veículo com tolerância configurável; eventos tardios vão para `late_events`
- [ ] Validação contra `/v2/arrivals/by_stop/:id` (observed_arrival oficial)

## Fase 5 — Agregações incrementais
- [ ] *Continuous aggregates* do TimescaleDB: atraso por linha × hora, com atualização incremental
- [ ] Vistas por dia da semana × hora (*heatmap*) e percentis p50/p90
- [ ] Exportação para DuckDB/Parquet, para análise offline

## Fase 6 — Mapa ao vivo e dashboard
- [ ] FastAPI: `GET /api/vehicles` (snapshot) + `GET /api/stream` (SSE)
- [ ] Mapa com MapLibre GL, interpolação suave entre posições e cor pelo atraso
- [ ] Página de análises (atraso por linha, *heatmap* hora × dia)

## Fase 7 — Observabilidade, testes e README final
- [ ] Latência ponta a ponta: `ts_veículo → ts_coletor → ts_kafka → ts_bd → ts_browser`
- [ ] Testes: unitários, propriedades (duplicados/ordem) e integração com `docker compose`
- [ ] README com capturas de ecrã e números medidos
