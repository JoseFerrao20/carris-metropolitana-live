"""Abstração mínima do log de eventos: Redpanda/Kafka em produção, memória nos testes."""

from __future__ import annotations

import asyncio
import zlib
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Record:
    topic: str
    key: bytes | None
    value: bytes
    partition: int = 0
    offset: int = 0
    timestamp_ms: int = 0


class Producer(Protocol):
    async def send(self, topic: str, key: bytes, value: bytes) -> None: ...
    async def flush(self) -> None: ...


class KafkaProducer:
    """Produtor idempotente (``enable_idempotence``): retries do cliente não duplicam no log."""

    def __init__(self, bootstrap: str) -> None:
        from aiokafka import AIOKafkaProducer

        self._p = AIOKafkaProducer(
            bootstrap_servers=bootstrap,
            enable_idempotence=True,
            acks="all",
            linger_ms=50,
            compression_type="lz4",
        )

    async def start(self) -> None:
        await self._p.start()

    async def stop(self) -> None:
        await self._p.stop()

    async def send(self, topic: str, key: bytes, value: bytes) -> None:
        await self._p.send(topic, key=key, value=value)

    async def flush(self) -> None:
        await self._p.flush()


class MemoryBus:
    """Log em memória com a mesma semântica de partições por chave (para testes)."""

    def __init__(self, partitions: int = 3) -> None:
        self.partitions = partitions
        self.logs: dict[str, list[list[Record]]] = defaultdict(
            lambda: [[] for _ in range(partitions)]
        )
        self._new = asyncio.Event()

    def _partition(self, key: bytes | None) -> int:
        return 0 if key is None else zlib.crc32(key) % self.partitions

    async def send(self, topic: str, key: bytes, value: bytes) -> None:
        p = self._partition(key)
        log = self.logs[topic][p]
        log.append(Record(topic, key, value, p, len(log)))
        self._new.set()

    async def flush(self) -> None:
        return None

    def all(self, topic: str) -> list[Record]:
        return [r for part in self.logs[topic] for r in part]

    async def consume(
        self, topic: str, start: dict[int, int] | None = None
    ) -> AsyncIterator[Record]:
        pos = dict(start or {})
        while True:
            progressed = False
            for p, log in enumerate(self.logs[topic]):
                i = pos.get(p, 0)
                while i < len(log):
                    yield log[i]
                    i += 1
                    progressed = True
                pos[p] = i
            if not progressed:
                self._new.clear()
                await self._new.wait()
