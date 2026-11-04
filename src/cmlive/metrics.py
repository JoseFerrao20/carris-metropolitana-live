"""Métricas Prometheus partilhadas pelos serviços."""

from prometheus_client import Counter, Gauge, Histogram

POLLS = Counter("cm_polls_total", "Pedidos à API", ["outcome"])
SOURCE_UP = Gauge("cm_source_up", "1 se o último poll teve sucesso")
VEHICLES_SEEN = Gauge("cm_vehicles_in_response", "Veículos na última resposta")
EVENTS_EMITTED = Counter("cm_events_emitted_total", "Posições novas publicadas no log")
EVENTS_DUPLICATE = Counter("cm_events_duplicate_total", "Posições repetidas descartadas no coletor")
EVENTS_REJECTED = Counter("cm_events_rejected_total", "Posições inválidas", ["reason"])
SOURCE_LAG = Histogram(
    "cm_source_lag_seconds",
    "Idade da posição quando chega ao coletor (collected_at - ts)",
    buckets=(1, 2, 5, 10, 15, 20, 30, 45, 60, 90, 120, 300),
)

ROWS_INGESTED = Counter("cm_rows_ingested_total", "Linhas novas na BD", ["table"])
ROWS_CONFLICT = Counter("cm_rows_conflict_total", "Linhas ignoradas por já existirem", ["table"])
INGEST_LAG = Histogram(
    "cm_ingest_lag_seconds",
    "collected_at -> commit na BD",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)

ARRIVALS = Counter("cm_arrivals_total", "Chegadas detetadas", ["method"])
LATE_EVENTS = Counter("cm_late_events_total", "Eventos para lá do watermark (descartados)")
UNMATCHED = Counter("cm_arrivals_unmatched_total", "Chegadas sem horário GTFS", ["reason"])
