# API da Carris Metropolitana — o que foi confirmado

> Data da investigação: 2026-11-04.

## Fonte da verdade

A API pública é open-source. Os endpoints e o esquema abaixo foram confirmados no
código do servidor oficial (`github.com/carrismetropolitana/api`, `apps/server` e
`apps/sync-vehicles`), e não a partir de memória.

**Base URL:** `https://api.carrismetropolitana.pt/v2/`

| Endpoint | Formato | Cache HTTP | Uso neste projeto |
|---|---|---|---|
| `GET /vehicles` | JSON (array) | `public, max-age=5` | Fonte principal do coletor |
| `GET /vehicles.pb` | GTFS-RT `FeedMessage` (protobuf) | `public, max-age=5` | Alternativa normalizada (só viagens com `trip_id` e < 90 s) |
| `GET /gtfs` | ZIP GTFS | — | Horários planeados (stop_times, trips, calendar_dates) |
| `GET /stops`, `/lines`, `/routes` | JSON | — | Metadados para o mapa e as análises |
| `GET /patterns/:id`, `/shapes/:id` | JSON | — | Traçados das linhas no mapa |
| `GET /arrivals/by_stop/:id` | JSON | — | **Validação**: tem `scheduled/estimated/observed_arrival` oficiais |
| `GET /alerts` | JSON (GTFS-RT Service Alerts) | — | Contexto opcional (perturbações) |

O `max-age=5` diz-nos qual é o intervalo de polling útil: pedir mais do que uma
vez a cada 5 s só devolve a mesma resposta da cache.

**GTFS:** o README do repositório `carrismetropolitana/gtfs` indica como URL
canónico `https://api.carrismetropolitana.pt/gtfs` (sem `/v2`), e o README da API
indica `/v2/gtfs`. O `gtfs-loader` tenta os dois, por esta ordem. Licença dos dados: CC BY 4.0.

## Esquema de `/vehicles` (campos usados)

Confirmado em `packages/types/src/api/vehicles.ts` (`interface Vehicle`):

```text
id                    "41|1160"   (agency_id|vehicle_id), chave de partição
timestamp             última posição conhecida (ver nota abaixo)
lat, lon, bearing, speed
trip_id, route_id, line_id, pattern_id, direction_id
stop_id               paragem que o veículo está a servir / a que se aproxima
current_status        INCOMING_AT | STOPPED_AT | IN_TRANSIT_TO
schedule_relationship SCHEDULED | ...
event_id              id do evento na origem
agency_id             41 | 42 | 43 | 44 (quatro operadores)
```

## Armadilhas encontradas na investigação

1. **Unidade do `timestamp` inconsistente.** O README oficial diz "milissegundos
   com precisão de segundos", mas o exemplo do mesmo README mostra
   `1729621800` (segundos). O código atual (`convertToProtobuf`) divide por 1000,
   ou seja, trata-o como ms. **O coletor normaliza os dois casos** (`> 1e12` ⇒ ms).
2. **Campos que podem vir a `null`.** Na implementação atual, `block_id`,
   `shift_id`, `license_plate` e as capacidades vêm `null` ou `0`. Nenhuma lógica
   pode depender deles.
3. **`pattern_id` vem do `shape_id` da origem** (`pattern_id: cmVehiclePosition.shape_id`).
   Não se confia nele para fazer o *join* com o GTFS: usa-se o `trip_id`.
4. **A origem real é o hub GO da TML** (`go.tmlmobilidade.pt/hub/api/v1/LA3SO/vehicles/positions`).
   A API da CM é uma fachada com cache. Pode haver posições repetidas entre polls,
   e por isso a deduplicação é obrigatória.
5. **O `/vehicles` devolve 404 com `[]`** quando a cache interna está vazia. Isto
   conta como "API indisponível", não como "zero veículos".

## Acesso a partir do ambiente de desenvolvimento

Nesta sessão, a política de rede **bloqueia** `api.carrismetropolitana.pt` e
`go.tmlmobilidade.pt` (o proxy responde 403 ao CONNECT). Consequências:

- O código é escrito contra o esquema confirmado acima e testado com *fixtures*
  baseadas nos exemplos oficiais.
- Nenhum número de volume ou latência no README é inventado: os valores reais
  são medidos ao correr o `docker compose` numa máquina com acesso à Internet
  (`make bench`).
