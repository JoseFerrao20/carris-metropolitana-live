"""Serviços de longa duração que ligam o log de eventos à base de dados."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from datetime import UTC, datetime

import orjson
import psycopg

from . import metrics as m
from .config import Settings
from .db.repo import INSERT_ARRIVAL, ScheduleRepo, apply_schema, insert_positions
from .delay import Arrival, ArrivalDetector
from .models import VehiclePosition

log = logging.getLogger(__name__)


def _dt(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


async def connect(settings: Settings, retries: int = 30) -> psycopg.AsyncConnection:
    for i in range(retries):
        try:
            return await psycopg.AsyncConnection.connect(settings.database_url)
        except psycopg.OperationalError as e:
            log.info("BD indisponível (%s); nova tentativa em 2 s", e)
            if i == retries - 1:
                raise
            await asyncio.sleep(2)
    raise RuntimeError("inalcançável")


def _consumer(settings: Settings, group: str, *topics: str):
    from aiokafka import AIOKafkaConsumer

    return AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.kafka_bootstrap,
        group_id=group,
        enable_auto_commit=False,  # commit manual, só depois de escrever na BD
        auto_offset_reset="earliest",
        max_poll_records=settings.ingest_batch_size,
    )


# --------------------------------------------------------------------------- ingestor


async def run_ingestor(settings: Settings, stop: asyncio.Event) -> None:
    """Kafka → ``vehicle_positions``. At-least-once + ``ON CONFLICT DO NOTHING``."""
    conn = await connect(settings)
    await apply_schema(conn)
    consumer = _consumer(settings, "ingestor", settings.topic_positions)
    await consumer.start()
    try:
        while not stop.is_set():
            batches = await consumer.getmany(
                timeout_ms=int(settings.ingest_flush_s * 1000),
                max_records=settings.ingest_batch_size,
            )
            records = [r for recs in batches.values() for r in recs]
            if not records:
                continue
            batch = []
            for r in records:
                try:
                    batch.append(VehiclePosition.from_json(r.value))
                except (orjson.JSONDecodeError, TypeError) as e:
                    log.warning("mensagem inválida em %s@%s: %s", r.partition, r.offset, e)
            new = await insert_positions(conn, batch)
            await conn.commit()
            await consumer.commit()  # só agora: um crash antes disto reprocessa (idempotente)
            now = time.time()
            for p in batch:
                m.INGEST_LAG.observe(max(0.0, now - p.collected_at))
            m.ROWS_INGESTED.labels("vehicle_positions").inc(new)
            m.ROWS_CONFLICT.labels("vehicle_positions").inc(len(batch) - new)
            log.debug("lote: %d mensagens, %d novas", len(batch), new)
    finally:
        await consumer.stop()
        await conn.close()


# --------------------------------------------------------------------------- motor de atrasos


class OffsetTracker:
    """Decide que offsets é seguro *commitar* enquanto há eventos retidos no ReorderBuffer.

    Um evento consumido no instante ``t`` é libertado pelo buffer até ``t + janela``
    (regra do relógio de parede). Por isso, os offsets consumidos antes de
    ``agora − janela − margem`` já foram processados e escritos.
    """

    def __init__(self, hold_s: float) -> None:
        self.hold_s = hold_s
        self.pending: dict[object, deque[tuple[float, int]]] = {}

    def seen(self, tp: object, offset: int, now: float) -> None:
        self.pending.setdefault(tp, deque()).append((now, offset))

    def committable(self, now: float) -> dict[object, int]:
        out = {}
        for tp, q in self.pending.items():
            last = None
            while q and q[0][0] <= now - self.hold_s:
                last = q.popleft()[1]
            if last is not None:
                out[tp] = last + 1  # Kafka: commit = próximo offset a ler
        return out


async def persist_arrivals(
    conn: psycopg.AsyncConnection, repo: ScheduleRepo, arrivals: list[Arrival]
) -> list[dict]:
    rows, out = [], []
    for a in arrivals:
        m.ARRIVALS.labels(a.method).inc()
        match, info = await repo.match(a.trip_id, a.stop_id, a.observed_ts)
        if match is None:
            m.UNMATCHED.labels(info).inc()
            log.debug("sem horário para %s/%s: %s", a.trip_id, a.stop_id, info)
            continue
        delay = round(match.delay_s)
        line_id = a.line_id or info.line_id
        rows.append(
            (
                _dt(match.scheduled_ts),
                a.trip_id,
                match.stop_sequence,
                match.service_date,
                a.stop_id,
                a.vehicle_id,
                line_id,
                a.route_id or info.route_id,
                _dt(a.observed_ts),
                delay,
                a.method,
                a.uncertainty_s,
            )
        )
        out.append(
            {
                "vehicle_id": a.vehicle_id,
                "trip_id": a.trip_id,
                "stop_id": a.stop_id,
                "line_id": line_id,
                "delay_s": delay,
                "observed_ts": a.observed_ts,
                "method": a.method,
            }
        )
    if rows:
        async with conn.cursor() as cur:
            await cur.executemany(INSERT_ARRIVAL, rows)
            new = max(cur.rowcount, 0)  # psycopg soma o rowcount de cada execução
        m.ROWS_INGESTED.labels("stop_arrivals").inc(new)
        m.ROWS_CONFLICT.labels("stop_arrivals").inc(len(rows) - new)
    await conn.commit()
    return out


async def run_delay_engine(settings: Settings, stop: asyncio.Event, producer=None) -> None:
    conn = await connect(settings)
    await apply_schema(conn)
    repo = ScheduleRepo(conn, settings.timezone)
    await repo.refresh_if_needed()
    detector = ArrivalDetector(
        window_s=settings.reorder_window_s,
        geofence_m=settings.geofence_m,
        stop_coords=repo.stop_coords,
    )
    offsets = OffsetTracker(hold_s=settings.reorder_window_s + 5)
    consumer = _consumer(settings, "delay-engine", settings.topic_positions)
    await consumer.start()
    late_seen = 0
    stats = {"consumed": 0, "arrivals": 0, "persisted": 0}
    last_log = time.monotonic()
    try:
        while not stop.is_set():
            batches = await consumer.getmany(timeout_ms=1000, max_records=5000)
            now = time.time()
            for tp, recs in batches.items():
                stats["consumed"] += len(recs)
                for r in recs:
                    with contextlib.suppress(orjson.JSONDecodeError, TypeError):
                        detector.push(VehiclePosition.from_json(r.value))
                    offsets.seen(tp, r.offset, now)
            await repo.refresh_if_needed()
            arrivals = detector.poll(now)
            if arrivals:
                stats["arrivals"] += len(arrivals)
                published = await persist_arrivals(conn, repo, arrivals)
                stats["persisted"] += len(published)
                if producer is not None:
                    for ev in published:
                        await producer.send(
                            settings.topic_arrivals, ev["vehicle_id"].encode(), orjson.dumps(ev)
                        )
            if detector.buffer.late > late_seen:
                m.LATE_EVENTS.inc(detector.buffer.late - late_seen)
                late_seen = detector.buffer.late
            if time.monotonic() - last_log > 10:
                log.info(
                    "motor de atrasos: %s, em buffer=%d, tardios=%d",
                    stats,
                    detector.buffer.pending(),
                    detector.buffer.late,
                )
                last_log = time.monotonic()
            commit = offsets.committable(time.time())
            if commit:
                await consumer.commit(commit)
    finally:
        await consumer.stop()
        await conn.close()
