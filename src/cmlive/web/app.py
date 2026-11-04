"""API web: snapshot, stream SSE para o mapa ao vivo e endpoints de análise."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from importlib import resources
from typing import Any

import orjson
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Histogram, generate_latest
from psycopg_pool import AsyncConnectionPool

from ..config import Settings, get_settings
from ..models import VehiclePosition

log = logging.getLogger(__name__)

E2E_LATENCY = Histogram(
    "cm_e2e_latency_seconds",
    "Latência medida no browser",
    ["stage"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 45, 60, 90, 120),
)


class LiveState:
    """Último estado de cada veículo + fan-out para os clientes SSE."""

    def __init__(self, max_age_s: int = 300) -> None:
        self.vehicles: dict[str, dict[str, Any]] = {}
        self.delays: dict[str, int] = {}  # vehicle_id -> último atraso conhecido
        self.dirty: set[str] = set()
        self.clients: set[asyncio.Queue[bytes]] = set()
        self.max_age_s = max_age_s

    def update_position(self, pos: VehiclePosition, log_ts: float | None = None) -> None:
        prev = self.vehicles.get(pos.vehicle_id)
        if prev and prev["ts"] >= pos.ts:
            return  # fora de ordem ou repetido: o mapa só avança
        d = asdict(pos)
        d["log_ts"] = log_ts
        d["delay_s"] = self.delays.get(pos.vehicle_id) if pos.trip_id else None
        self.vehicles[pos.vehicle_id] = d
        self.dirty.add(pos.vehicle_id)

    def update_delay(self, ev: dict) -> None:
        vid = ev["vehicle_id"]
        self.delays[vid] = ev["delay_s"]
        if vid in self.vehicles:
            self.vehicles[vid]["delay_s"] = ev["delay_s"]
            self.dirty.add(vid)

    def prune(self, now: float) -> list[str]:
        gone = [v for v, d in self.vehicles.items() if now - d["ts"] > self.max_age_s]
        for v in gone:
            self.vehicles.pop(v, None)
            self.delays.pop(v, None)
        return gone

    def snapshot(self) -> list[dict]:
        return list(self.vehicles.values())

    def tick(self, now: float) -> bytes | None:
        gone = self.prune(now)
        if not self.dirty and not gone:
            return None
        msg = {
            "type": "delta",
            "sent_at": now,
            "vehicles": [self.vehicles[v] for v in self.dirty if v in self.vehicles],
            "removed": gone,
        }
        self.dirty.clear()
        return b"event: delta\ndata: " + orjson.dumps(msg) + b"\n\n"

    def broadcast(self, payload: bytes) -> None:
        for q in list(self.clients):
            if q.full():  # cliente lento: descarta o mais antigo em vez de bloquear todos
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(payload)


async def _consume_bus(settings: Settings, state: LiveState) -> None:
    from aiokafka import AIOKafkaConsumer

    while True:
        consumer = AIOKafkaConsumer(
            settings.topic_positions,
            settings.topic_arrivals,
            bootstrap_servers=settings.kafka_bootstrap,
            group_id=None,
            auto_offset_reset="latest",
        )
        try:
            await consumer.start()
            async for r in consumer:
                if r.topic == settings.topic_positions:
                    state.update_position(VehiclePosition.from_json(r.value), r.timestamp / 1000)
                else:
                    state.update_delay(orjson.loads(r.value))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # broker em baixo: tenta outra vez
            log.warning("consumidor do mapa: %s; a religar em 5 s", e)
            await asyncio.sleep(5)
        finally:
            await consumer.stop()


async def _ticker(state: LiveState, interval: float = 1.0) -> None:
    while True:
        await asyncio.sleep(interval)
        payload = state.tick(time.time())
        if payload:
            state.broadcast(payload)


async def _warm_start(pool: AsyncConnectionPool, state: LiveState) -> None:
    """Preenche o mapa com a última posição de cada veículo (últimos 5 min)."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("""
            SELECT DISTINCT ON (vehicle_id) vehicle_id, extract(epoch FROM ts)::bigint, lat, lon,
                   bearing, speed, trip_id, line_id, route_id, stop_id, current_status, agency_id,
                   extract(epoch FROM collected_at)::float8
            FROM vehicle_positions WHERE ts > now() - interval '5 minutes'
            ORDER BY vehicle_id, ts DESC""")
        for row in await cur.fetchall():
            state.update_position(VehiclePosition(*row))
    state.dirty.clear()


def create_app(settings: Settings | None = None, with_background: bool = True) -> FastAPI:
    settings = settings or get_settings()
    state = LiveState(settings.stale_after_s)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pool = AsyncConnectionPool(settings.database_url, open=False, min_size=1)
        tasks: list[asyncio.Task] = []
        await app.state.pool.open(wait=False)
        if with_background:
            with contextlib.suppress(Exception):
                await _warm_start(app.state.pool, state)
            tasks = [
                asyncio.create_task(_consume_bus(settings, state)),
                asyncio.create_task(_ticker(state)),
            ]
        yield
        for t in tasks:
            t.cancel()
        await app.state.pool.close()

    app = FastAPI(title="Carris Metropolitana Live", lifespan=lifespan)
    app.state.live = state

    def _page(name: str) -> HTMLResponse:
        html = resources.files("cmlive.web").joinpath("static", name).read_text()
        return HTMLResponse(html)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return _page("index.html")

    @app.get("/analytics", response_class=HTMLResponse)
    async def analytics_page():
        return _page("analytics.html")

    @app.get("/api/vehicles")
    async def vehicles():
        return Response(
            orjson.dumps({"server_time": time.time(), "vehicles": state.snapshot()}),
            media_type="application/json",
        )

    @app.get("/api/stream")
    async def stream(request: Request):
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=30)
        state.clients.add(q)

        async def gen():
            try:
                snap = {"type": "snapshot", "sent_at": time.time(), "vehicles": state.snapshot()}
                yield b"retry: 3000\nevent: snapshot\ndata: " + orjson.dumps(snap) + b"\n\n"
                while not await request.is_disconnected():
                    try:
                        yield await asyncio.wait_for(q.get(), timeout=15)
                    except TimeoutError:
                        yield b": keep-alive\n\n"
            finally:
                state.clients.discard(q)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
        )

    @app.post("/api/latency")
    async def latency(samples: dict[str, list[float]]):
        """O browser reporta amostras de latência ponta a ponta (por etapa)."""
        for stage, values in samples.items():
            if stage not in {"vehicle_to_browser", "collector_to_browser", "log_to_browser"}:
                continue
            for v in values[:500]:
                if 0 <= v < 3600:
                    E2E_LATENCY.labels(stage).observe(v)
        return {"ok": True}

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    async def _query(sql: str, params: tuple | dict = ()) -> list[dict]:
        async with app.state.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(sql, params)
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in await cur.fetchall()]

    def _json(data: Any) -> Response:
        return Response(orjson.dumps(data, default=str), media_type="application/json")

    tz = settings.timezone

    @app.get("/api/analytics/lines")
    async def by_line(days: int = Query(7, ge=1, le=3650), min_n: int = 20):
        rows = await _query(
            """SELECT line_id, sum(n)::int AS n,
                      round((sum(avg_delay_s * n) / sum(n))::numeric, 1)::float AS avg_delay_s,
                      round(100.0 * sum(n_on_time) / sum(n), 1)::float AS pct_on_time,
                      round(100.0 * sum(n_late) / sum(n), 1)::float AS pct_late,
                      round(100.0 * sum(n_early) / sum(n), 1)::float AS pct_early
               FROM delay_hourly
               WHERE bucket > now() - make_interval(days => %s)
               GROUP BY line_id HAVING sum(n) >= %s
               ORDER BY avg_delay_s DESC""",
            (days, min_n),
        )
        return _json(rows)

    @app.get("/api/analytics/heatmap")
    async def heatmap(days: int = Query(28, ge=1, le=3650), line_id: str | None = None):
        rows = await _query(
            """SELECT extract(isodow FROM bucket AT TIME ZONE %(tz)s)::int AS dow,
                       extract(hour FROM bucket AT TIME ZONE %(tz)s)::int AS hour,
                       sum(n)::int AS n,
                       round((sum(avg_delay_s * n) / sum(n))::numeric, 1)::float AS avg_delay_s,
                       round(100.0 * sum(n_on_time) / sum(n), 1)::float AS pct_on_time
                FROM delay_hourly
                WHERE bucket > now() - make_interval(days => %(days)s)
                  AND (%(line)s::text IS NULL OR line_id = %(line)s)
                GROUP BY 1, 2 ORDER BY 1, 2""",
            {"days": days, "line": line_id, "tz": tz},
        )
        return _json(rows)

    @app.get("/api/analytics/stops")
    async def by_stop(line_id: str, days: int = Query(7, ge=1, le=60)):
        rows = await _query(
            """SELECT a.stop_id, s.name, min(a.stop_sequence) AS stop_sequence,
                      count(*)::int AS n,
                      round(avg(a.delay_s)::numeric, 1)::float AS avg_delay_s,
                      percentile_cont(0.5) WITHIN GROUP (ORDER BY a.delay_s) AS p50_delay_s,
                      percentile_cont(0.9) WITHIN GROUP (ORDER BY a.delay_s) AS p90_delay_s
               FROM stop_arrivals a LEFT JOIN gtfs.stops s USING (stop_id)
               WHERE a.line_id = %s AND a.scheduled_at > now() - make_interval(days => %s)
                 AND a.uncertainty_s <= 60
               GROUP BY a.stop_id, s.name ORDER BY stop_sequence""",
            (line_id, days),
        )
        return _json(rows)

    @app.get("/api/stats")
    async def stats():
        rows = await _query("""
            SELECT
              (SELECT count(*) FROM vehicle_positions WHERE ts > now() - interval '24 hours')
                  AS positions_24h,
              (SELECT count(DISTINCT vehicle_id) FROM vehicle_positions
                  WHERE ts > now() - interval '10 minutes') AS vehicles_10min,
              (SELECT count(*) FROM stop_arrivals WHERE scheduled_at > now() - interval '24 hours')
                  AS arrivals_24h,
              (SELECT pg_size_pretty(hypertable_size('vehicle_positions'))) AS positions_size,
              (SELECT pg_size_pretty(hypertable_size('stop_arrivals'))) AS arrivals_size,
              (SELECT min(ts) FROM vehicle_positions) AS first_position,
              (SELECT percentile_cont(ARRAY[0.5, 0.95]) WITHIN GROUP (
                      ORDER BY extract(epoch FROM ingested_at - collected_at))
                 FROM vehicle_positions WHERE ts > now() - interval '1 hour')
                  AS collector_to_db_p50_p95_s,
              (SELECT percentile_cont(ARRAY[0.5, 0.95]) WITHIN GROUP (
                      ORDER BY extract(epoch FROM collected_at - ts))
                 FROM vehicle_positions WHERE ts > now() - interval '1 hour')
                  AS vehicle_to_collector_p50_p95_s
        """)
        out = rows[0]
        out["live_vehicles"] = len(state.vehicles)
        out["sse_clients"] = len(state.clients)
        return _json(out)

    return app
