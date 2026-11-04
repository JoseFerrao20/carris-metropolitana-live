"""Cliente HTTP resiliente para ``/v2/vehicles``."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx
import orjson

log = logging.getLogger(__name__)


class SourceUnavailable(Exception):
    """A fonte não devolveu dados utilizáveis (rede, 5xx, 404 com cache vazia, JSON inválido)."""


class BreakerOpen(SourceUnavailable):
    """O circuit breaker está aberto: nem sequer tentámos."""


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Abre após ``threshold`` falhas seguidas; ao fim de ``reset_s`` deixa passar uma sonda."""

    threshold: int = 5
    reset_s: float = 60.0
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        self.failures = 0
        self.state = BreakerState.CLOSED
        self.opened_at = 0.0

    def allow(self) -> bool:
        if self.state is BreakerState.OPEN:
            if self.clock() - self.opened_at >= self.reset_s:
                self.state = BreakerState.HALF_OPEN
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.state = BreakerState.CLOSED

    def record_failure(self) -> None:
        self.failures += 1
        if self.state is BreakerState.HALF_OPEN or self.failures >= self.threshold:
            if self.state is not BreakerState.OPEN:
                log.warning("circuit breaker aberto após %d falhas", self.failures)
            self.state = BreakerState.OPEN
            self.opened_at = self.clock()


def backoff_delay(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    """Backoff exponencial com *full jitter* (AWS Architecture Blog)."""
    return random.uniform(0, min(cap, base * 2**attempt))


class VehicleSource:
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        *,
        max_retries: int = 4,
        breaker: CircuitBreaker | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.client = client
        self.url = base_url.rstrip("/") + "/vehicles"
        self.max_retries = max_retries
        self.breaker = breaker or CircuitBreaker()
        self._sleep = sleep
        self.last_ok: float | None = None

    async def _fetch_once(self) -> list[dict[str, Any]]:
        try:
            r = await self.client.get(self.url, headers={"accept": "application/json"})
        except httpx.HTTPError as e:
            raise SourceUnavailable(f"erro de rede: {e!r}") from e
        # O servidor oficial responde 404 + [] quando a sua cache interna está vazia.
        if r.status_code == 404:
            raise SourceUnavailable("404: cache da API vazia")
        if r.status_code >= 500 or r.status_code == 429:
            raise SourceUnavailable(f"HTTP {r.status_code}")
        if r.status_code != 200:
            raise SourceUnavailable(f"HTTP inesperado {r.status_code}")
        try:
            data = orjson.loads(r.content)
        except orjson.JSONDecodeError as e:
            raise SourceUnavailable("JSON inválido") from e
        if not isinstance(data, list):
            raise SourceUnavailable(f"esperava lista, recebi {type(data).__name__}")
        if not data:
            raise SourceUnavailable("lista vazia")
        return data

    async def fetch(self) -> list[dict[str, Any]]:
        if not self.breaker.allow():
            raise BreakerOpen("circuit breaker aberto")
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                data = await self._fetch_once()
            except SourceUnavailable as e:
                last_exc = e
                log.info("tentativa %d falhou: %s", attempt + 1, e)
                if attempt < self.max_retries:
                    await self._sleep(backoff_delay(attempt))
                continue
            self.breaker.record_success()
            self.last_ok = time.time()
            return data
        self.breaker.record_failure()
        raise SourceUnavailable(str(last_exc)) from last_exc
