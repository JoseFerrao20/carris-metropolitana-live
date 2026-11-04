"""Coletor: faz polling de ``/v2/vehicles`` e publica posições **novas** no log de eventos."""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import orjson

from . import metrics as m
from .bus import Producer
from .models import VehiclePosition, parse_vehicle
from .source import BreakerOpen, SourceUnavailable, VehicleSource

log = logging.getLogger(__name__)


@dataclass
class Deduplicator:
    """Guarda o último ``ts`` publicado por veículo.

    A API tem cache de 5 s e a origem (hub GO) só atualiza cada veículo a cada
    10–30 s, por isso a maioria das posições de cada resposta é repetida.
    Também descarta regressões (``ts`` mais antigo do que o último visto), que
    acontecem quando um nó da cache serve uma resposta mais velha.
    """

    ttl_s: int = 3600
    last: dict[str, int] = field(default_factory=dict)
    seen_at: dict[str, float] = field(default_factory=dict)

    def is_new(self, pos: VehiclePosition) -> bool:
        prev = self.last.get(pos.vehicle_id)
        if prev is not None and pos.ts <= prev:
            return False
        self.last[pos.vehicle_id] = pos.ts
        self.seen_at[pos.vehicle_id] = pos.collected_at
        return True

    def evict(self, now: float) -> int:
        old = [v for v, t in self.seen_at.items() if now - t > self.ttl_s]
        for v in old:
            self.last.pop(v, None)
            self.seen_at.pop(v, None)
        return len(old)


class NdjsonRecorder:
    """Grava as respostas em bruto (gzip, um ficheiro por hora) para replay e testes."""

    def __init__(self, directory: str) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def write(self, collected_at: float, payload: list[dict]) -> None:
        name = time.strftime("vehicles-%Y%m%d-%H.ndjson.gz", time.gmtime(collected_at))
        line = orjson.dumps({"collected_at": collected_at, "vehicles": payload}) + b"\n"
        with gzip.open(self.dir / name, "ab") as f:
            f.write(line)


@dataclass
class PollResult:
    received: int = 0
    emitted: int = 0
    duplicates: int = 0
    rejected: int = 0
    error: str | None = None


class Collector:
    def __init__(
        self,
        source: VehicleSource,
        producer: Producer,
        topic: str,
        *,
        stale_after_s: int = 300,
        recorder: NdjsonRecorder | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.source = source
        self.producer = producer
        self.topic = topic
        self.stale_after_s = stale_after_s
        self.recorder = recorder
        self.dedup = Deduplicator()
        self.clock = clock

    async def process(self, payload: list[dict], collected_at: float) -> PollResult:
        res = PollResult(received=len(payload))
        for raw in payload:
            if not isinstance(raw, dict):
                res.rejected += 1
                m.EVENTS_REJECTED.labels("not_object").inc()
                continue
            pos, reason = parse_vehicle(
                raw, collected_at=collected_at, stale_after_s=self.stale_after_s
            )
            if pos is None:
                res.rejected += 1
                m.EVENTS_REJECTED.labels(reason).inc()
                continue
            if not self.dedup.is_new(pos):
                res.duplicates += 1
                continue
            await self.producer.send(self.topic, pos.vehicle_id.encode(), pos.to_json())
            m.SOURCE_LAG.observe(max(0.0, collected_at - pos.ts))
            res.emitted += 1
        await self.producer.flush()
        m.EVENTS_EMITTED.inc(res.emitted)
        m.EVENTS_DUPLICATE.inc(res.duplicates)
        return res

    async def poll_once(self) -> PollResult:
        try:
            payload = await self.source.fetch()
        except BreakerOpen as e:
            m.POLLS.labels("breaker_open").inc()
            m.SOURCE_UP.set(0)
            return PollResult(error=str(e))
        except SourceUnavailable as e:
            m.POLLS.labels("error").inc()
            m.SOURCE_UP.set(0)
            log.warning("fonte indisponível: %s", e)
            return PollResult(error=str(e))
        collected_at = self.clock()
        m.POLLS.labels("ok").inc()
        m.SOURCE_UP.set(1)
        m.VEHICLES_SEEN.set(len(payload))
        if self.recorder:
            self.recorder.write(collected_at, payload)
        res = await self.process(payload, collected_at)
        self.dedup.evict(collected_at)
        return res

    async def run(self, interval_s: float, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        while not stop.is_set():
            started = time.monotonic()
            res = await self.poll_once()
            log.info(
                "poll: recebidos=%d novos=%d repetidos=%d rejeitados=%d erro=%s",
                res.received,
                res.emitted,
                res.duplicates,
                res.rejected,
                res.error,
            )
            # Intervalo fixo entre inícios de poll (não acumula atraso).
            wait = max(0.0, interval_s - (time.monotonic() - started))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=wait)
