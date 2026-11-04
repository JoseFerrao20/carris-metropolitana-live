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

## Confirmado com dados reais (2026-11-04, ~17:15 UTC)

Depois de o domínio ter sido autorizado, verifiquei tudo contra a API real:

| O quê | Documentação / código antigo | Realidade |
|---|---|---|
| `timestamp` | "ms" no texto, segundos no exemplo | **milissegundos** (`1793812304000`) |
| `id` do veículo | `"41\|1160"` | `"[LA77N]1886"` (`[operador]número`) |
| `trip_id` | `1503_0_2_..._21NBI` | `[7DQC0][LA77N]1252_0_3_1700_1729_0_1` ou `[FBZQZ][A2L1N]4001_0_3\|1000\|0710` |
| `stop_id` | igual ao GTFS | **ids antigos** (`030037`), e o GTFS atual usa `330037` |
| paragem desconhecida | — | sentinela literal `"UNAVAILABLE_STOP_ID"` |
| coordenadas | — | algumas posições vêm a `(0, 0)` |
| `/gtfs` | URL canónico | `307` → `/v2/gtfs` |
| GTFS | publicado pela CM | publicado pela **TML (plataforma GO)**, com `plans.txt` e `legacy_ids` em `stops.txt` |

Consequências no código:

- **`trip_id` mantém-se completo.** Com os prefixos `[plano][operador]`, 1117/1117
  viagens do tempo real existem tal e qual no GTFS. A versão anterior retirava o
  prefixo e teria partido o *join* com o horário.
- **`stop_id` convertido via `stops.legacy_ids`.** Sem conversão, só 58% dos pares
  (viagem, paragem) do tempo real existiam no GTFS; com a conversão, 97,7%. O que
  sobra é `UNAVAILABLE_STOP_ID`, tratado como "sem paragem" (não conta como
  passagem pela paragem anterior).
- **A linha** vem de `routes.route_short_name` (o GTFS da TML não tem `line_id`).

## Acesso a partir do ambiente de desenvolvimento

Na primeira fase deste trabalho, a política de rede **bloqueava** `api.carrismetropolitana.pt`
(o proxy respondia 403 ao CONNECT). Na altura:

- O código é escrito contra o esquema confirmado acima e testado com *fixtures*
  baseadas nos exemplos oficiais.
- Nenhum número de volume ou latência no README é inventado: os valores reais
  são medidos ao correr o `docker compose` numa máquina com acesso à Internet
  (`make bench`).
