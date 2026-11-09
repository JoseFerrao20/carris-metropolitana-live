"""Configuração por variáveis de ambiente (prefixo ``CMLIVE_``)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CMLIVE_", env_file=".env", extra="ignore")

    # Fonte
    api_base_url: str = "https://api.carrismetropolitana.pt/v2"
    gtfs_urls: tuple[str, ...] = (
        "https://api.carrismetropolitana.pt/gtfs",
        "https://api.carrismetropolitana.pt/v2/gtfs",
    )
    poll_interval_s: float = 5.0  # a API serve com cache-control: max-age=5
    http_timeout_s: float = 10.0
    max_retries: int = 4
    breaker_failure_threshold: int = 5
    breaker_reset_s: float = 60.0
    stale_after_s: int = 300  # posições mais velhas do que isto são descartadas

    # Log de eventos
    kafka_bootstrap: str = "localhost:19092"
    topic_positions: str = "vehicle-positions"
    topic_arrivals: str = "stop-arrivals"
    kafka_group_prefix: str = ""  # isola consumer groups (ex.: testes ao lado da produção)

    # Base de dados
    database_url: str = "postgresql://cmlive:cmlive@localhost:5432/cmlive"
    ingest_batch_size: int = 2000
    ingest_flush_s: float = 1.0

    # Motor de atrasos
    reorder_window_s: int = 20  # tolerância a eventos fora de ordem
    geofence_m: float = 40.0
    timezone: str = "Europe/Lisbon"

    # Autenticação
    session_days: int = 30
    cookie_secure: bool = False  # ponha CMLIVE_COOKIE_SECURE=true atrás de HTTPS

    # Frontend compilado; vazio = src/cmlive/web/dist (dentro do pacote)
    frontend_dist: str = ""

    # Gravação NDJSON (replay/testes); vazio = desligado
    record_dir: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
