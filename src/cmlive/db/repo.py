"""Acesso à base de dados para os serviços em streaming (psycopg 3, async)."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from importlib import resources
from zoneinfo import ZoneInfo

import psycopg

from ..gtfs_time import ScheduleMatch, StopTime, resolve_schedule
from ..models import VehiclePosition

log = logging.getLogger(__name__)


async def apply_schema(conn: psycopg.AsyncConnection) -> None:
    """Aplica o esquema numa transação, com um lock para os serviços não colidirem."""
    sql = resources.files("cmlive.db").joinpath("schema.sql").read_text()
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext('cmlive-schema'))")
    await conn.execute(sql)
    await conn.commit()


def _dt(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


INSERT_POSITIONS = """
INSERT INTO vehicle_positions
    (ts, vehicle_id, lat, lon, bearing, speed, trip_id, line_id, route_id, stop_id,
     current_status, agency_id, collected_at)
SELECT * FROM unnest(
    %s::timestamptz[], %s::text[], %s::float8[], %s::float8[], %s::real[], %s::real[],
    %s::text[], %s::text[], %s::text[], %s::text[], %s::text[], %s::text[], %s::timestamptz[])
ON CONFLICT (vehicle_id, ts) DO NOTHING
"""


async def insert_positions(conn: psycopg.AsyncConnection, batch: list[VehiclePosition]) -> int:
    """Insere em lote; devolve quantas linhas eram novas (o resto eram duplicados)."""
    if not batch:
        return 0
    cols = list(
        zip(
            *(
                (
                    _dt(p.ts),
                    p.vehicle_id,
                    p.lat,
                    p.lon,
                    p.bearing,
                    p.speed,
                    p.trip_id,
                    p.line_id,
                    p.route_id,
                    p.stop_id,
                    p.current_status,
                    p.agency_id,
                    _dt(p.collected_at),
                )
                for p in batch
            ),
            strict=True,
        )
    )
    async with conn.cursor() as cur:
        await cur.execute(INSERT_POSITIONS, [list(c) for c in cols])
        return cur.rowcount


@dataclass(frozen=True, slots=True)
class TripInfo:
    service_id: str
    route_id: str | None
    line_id: str | None
    stop_times: tuple[StopTime, ...]


class ScheduleRepo:
    """Horários GTFS com cache LRU por viagem. Invalida a cache quando o feed muda."""

    def __init__(self, conn: psycopg.AsyncConnection, tz: str, max_trips: int = 20_000) -> None:
        self.conn = conn
        self.tz = ZoneInfo(tz)
        self.max_trips = max_trips
        self._trips: OrderedDict[str, TripInfo | None] = OrderedDict()
        self._dates: dict[str, set[date]] = {}
        self.stops: dict[str, tuple[float, float]] = {}
        self.feed_version: str | None = None
        self._checked = 0.0

    async def refresh_if_needed(self, every_s: float = 300) -> None:
        if time.monotonic() - self._checked < every_s and self.feed_version:
            return
        self._checked = time.monotonic()
        async with self.conn.cursor() as cur:
            await cur.execute("SELECT to_regclass('gtfs.stop_times')")
            if (await cur.fetchone())[0] is None:
                log.warning("GTFS ainda não carregado")
                return
            await cur.execute("SELECT feed_version FROM gtfs.feed_info LIMIT 1")
            row = await cur.fetchone()
            version = row[0] if row else None
            if version == self.feed_version:
                return
            await cur.execute("SELECT stop_id, lat, lon FROM gtfs.stops WHERE lat IS NOT NULL")
            self.stops = {s: (lat, lon) for s, lat, lon in await cur.fetchall()}
        await self.conn.commit()
        self._trips.clear()
        self._dates.clear()
        self.feed_version = version
        log.info("GTFS ativo: %s (%d paragens)", version, len(self.stops))

    def stop_coords(self, stop_id: str) -> tuple[float, float] | None:
        return self.stops.get(stop_id)

    async def trip(self, trip_id: str) -> TripInfo | None:
        if trip_id in self._trips:
            self._trips.move_to_end(trip_id)
            return self._trips[trip_id]
        async with self.conn.cursor() as cur:
            await cur.execute(
                """SELECT t.service_id, t.route_id, r.line_id
                   FROM gtfs.trips t LEFT JOIN gtfs.routes r USING (route_id)
                   WHERE t.trip_id = %s""",
                (trip_id,),
            )
            row = await cur.fetchone()
            info = None
            if row:
                await cur.execute(
                    "SELECT stop_sequence, stop_id, arrival_s FROM gtfs.stop_times "
                    "WHERE trip_id = %s ORDER BY stop_sequence",
                    (trip_id,),
                )
                sts = tuple(StopTime(*r) for r in await cur.fetchall())
                info = TripInfo(row[0], row[1], row[2], sts)
        await self.conn.commit()
        self._trips[trip_id] = info
        if len(self._trips) > self.max_trips:
            self._trips.popitem(last=False)
        return info

    async def active_dates(self, service_id: str, around: date) -> set[date]:
        if service_id not in self._dates:
            async with self.conn.cursor() as cur:
                await cur.execute(
                    """SELECT date, exception_type FROM gtfs.calendar_dates
                       WHERE service_id = %s AND date BETWEEN %s AND %s""",
                    (service_id, around - timedelta(days=7), around + timedelta(days=7)),
                )
                active: set[date] = set()
                for d, exc in await cur.fetchall():
                    (active.add if exc == 1 else active.discard)(d)
            await self.conn.commit()
            self._dates[service_id] = active
        return self._dates[service_id]

    async def match(
        self, trip_id: str, stop_id: str, observed_ts: float
    ) -> tuple[ScheduleMatch, TripInfo] | tuple[None, str]:
        info = await self.trip(trip_id)
        if info is None:
            return None, "unknown_trip"
        around = datetime.fromtimestamp(observed_ts, self.tz).date()
        dates = await self.active_dates(info.service_id, around)
        if not dates:
            return None, "service_inactive"
        m = resolve_schedule(info.stop_times, dates, stop_id, observed_ts, self.tz)
        if m is None:
            return None, "stop_not_in_trip_or_out_of_range"
        return m, info


INSERT_ARRIVAL = """
INSERT INTO stop_arrivals
    (scheduled_at, trip_id, stop_sequence, service_date, stop_id, vehicle_id, line_id,
     route_id, observed_at, delay_s, method, uncertainty_s)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (trip_id, stop_sequence, scheduled_at) DO NOTHING
"""
