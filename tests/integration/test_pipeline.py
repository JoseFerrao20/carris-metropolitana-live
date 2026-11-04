"""Teste ponta a ponta contra TimescaleDB e Redpanda reais (``make up-infra``).

Usa uma viagem **real** do GTFS carregado e gera uma trajetória **sintética** com
um atraso conhecido (+120 s), com duplicados e eventos fora de ordem, para verificar
o que o sistema promete: deduplicação, reordenação, cálculo do atraso,
idempotência no reprocessamento e agregação.
"""

from __future__ import annotations

import asyncio
import os
import random
import uuid
from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient

from cmlive.bus import KafkaProducer
from cmlive.config import Settings
from cmlive.gtfs_time import scheduled_epoch
from cmlive.models import VehiclePosition
from cmlive.services import run_delay_engine, run_ingestor
from cmlive.web.app import create_app

pytestmark = pytest.mark.integration

DB = os.environ.get("CMLIVE_DATABASE_URL", "postgresql://cmlive:cmlive@localhost:5432/cmlive")
KAFKA = os.environ.get("CMLIVE_KAFKA_BOOTSTRAP", "localhost:19092")
DELAY = 120


def _require_infra() -> None:
    try:
        with psycopg.connect(DB, connect_timeout=3) as c:
            if c.execute("SELECT to_regclass('gtfs.stop_times')").fetchone()[0] is None:
                pytest.skip("GTFS não carregado (python -m cmlive gtfs --zip data/gtfs.zip)")
    except psycopg.OperationalError:
        pytest.skip("TimescaleDB indisponível (make up-infra)")


ARR_SQL = "SELECT count(*) FROM stop_arrivals WHERE trip_id = %s AND vehicle_id = %s"


def _cleanup(trip_id: str) -> None:
    with psycopg.connect(DB) as c:
        c.execute("DELETE FROM stop_arrivals WHERE trip_id = %s OR line_id = 'TEST'", (trip_id,))
        c.execute("DELETE FROM vehicle_positions WHERE agency_id = '99'")
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("CALL refresh_continuous_aggregate('delay_hourly', NULL, NULL)")


def _pick_trip():
    from zoneinfo import ZoneInfo

    with psycopg.connect(DB) as c:
        trip_id, _service_id, d = c.execute("""
            SELECT t.trip_id, t.service_id, cd.date
            FROM gtfs.trips t JOIN gtfs.calendar_dates cd USING (service_id)
            WHERE cd.exception_type = 1
              AND (SELECT count(*) = count(DISTINCT arrival_s) AND count(*) BETWEEN 10 AND 30
                   FROM gtfs.stop_times st WHERE st.trip_id = t.trip_id)
            ORDER BY cd.date, t.trip_id LIMIT 1""").fetchone()
        stops = c.execute(
            "SELECT st.stop_sequence, st.stop_id, st.arrival_s, s.lat, s.lon "
            "FROM gtfs.stop_times st JOIN gtfs.stops s USING (stop_id) "
            "WHERE st.trip_id = %s ORDER BY st.stop_sequence",
            (trip_id,),
        ).fetchall()
    tz = ZoneInfo("Europe/Lisbon")
    return (
        trip_id,
        d,
        [(seq, sid, scheduled_epoch(d, arr, tz), lat, lon) for seq, sid, arr, lat, lon in stops],
    )


def _trajectory(vid: str, trip_id: str, stops) -> list[VehiclePosition]:
    """INCOMING_AT 10 s antes (~170 m antes da paragem, fora da geofence) e STOPPED_AT
    10 s depois, na paragem ⇒ chegada estimada = sched + DELAY."""
    out = []
    for _, sid, sched, lat, lon in stops:
        t = sched + DELAY
        for ts, status, dlat in ((t - 10, "INCOMING_AT", 0.0015), (t + 10, "STOPPED_AT", 0.0)):
            out.append(
                VehiclePosition(
                    vehicle_id=vid,
                    ts=int(ts),
                    lat=lat - dlat,
                    lon=lon,
                    bearing=None,
                    speed=None,
                    trip_id=trip_id,
                    line_id="TEST",
                    route_id=None,
                    stop_id=sid,
                    current_status=status,
                    agency_id="99",
                    collected_at=ts + 5,
                )
            )
    return out


async def _produce(events, topic):
    p = KafkaProducer(KAFKA)
    await p.start()
    try:
        for e in events:
            await p.send(topic, e.vehicle_id.encode(), e.to_json())
        await p.flush()
    finally:
        await p.stop()


async def _wait_for(sql, params, expected, timeout=60):
    async with await psycopg.AsyncConnection.connect(DB) as c:
        for _ in range(timeout * 2):
            n = (await (await c.execute(sql, params)).fetchone())[0]
            await c.commit()
            if n >= expected:
                return n
            await asyncio.sleep(0.5)
    return n


async def _run_services(settings, until):
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(run_ingestor(settings, stop)),
        asyncio.create_task(run_delay_engine(settings, stop)),
    ]
    try:
        return await until()
    finally:
        stop.set()
        await asyncio.wait(tasks, timeout=15)
        for t in tasks:
            if t.done() and t.exception():
                raise t.exception()


async def test_end_to_end_delay_dedup_reorder_idempotent():
    _require_infra()
    trip_id, service_date, stops = _pick_trip()
    vid = f"99|test-{uuid.uuid4().hex[:8]}"
    topic = f"test-positions-{uuid.uuid4().hex[:8]}"
    settings = Settings(
        database_url=DB,
        kafka_bootstrap=KAFKA,
        topic_positions=topic,
        topic_arrivals=f"{topic}-arrivals",
        reorder_window_s=30,
        kafka_group_prefix=f"test-{uuid.uuid4().hex[:8]}-",
    )
    clean = _trajectory(vid, trip_id, stops)
    _cleanup(trip_id)

    # Ruído: 30% de duplicados e baralhar dentro de blocos de 4 eventos (< janela de 30 s).
    rnd = random.Random(42)
    noisy = clean + rnd.sample(clean, k=len(clean) * 3 // 10)
    noisy.sort(key=lambda e: e.ts)
    chunks = [noisy[i : i + 4] for i in range(0, len(noisy), 4)]
    for ch in chunks:
        rnd.shuffle(ch)
    noisy = [e for ch in chunks for e in ch]

    await _produce(noisy, topic)

    async def until():
        n_pos = await _wait_for(
            "SELECT count(*) FROM vehicle_positions WHERE vehicle_id = %s", (vid,), len(clean)
        )
        n_arr = await _wait_for(ARR_SQL, (trip_id, vid), len(stops))
        return n_pos, n_arr

    n_pos, n_arr = await _run_services(settings, until)
    assert n_pos == len(clean), "duplicados não devem chegar à tabela de posições"
    assert n_arr == len(stops), "uma chegada por paragem"

    with psycopg.connect(DB) as c:
        rows = c.execute(
            "SELECT stop_sequence, delay_s, method, service_date FROM stop_arrivals "
            "WHERE vehicle_id = %s ORDER BY stop_sequence",
            (vid,),
        ).fetchall()
    assert [r[0] for r in rows] == [s[0] for s in stops]
    assert {r[1] for r in rows} == {DELAY}
    assert {r[2] for r in rows} == {"stopped"}
    assert {r[3] for r in rows} == {service_date}

    # Reprocessar tudo outra vez (ex.: offsets perdidos) não cria linhas novas.
    topic2 = f"{topic}-replay"
    await _produce(noisy, topic2)
    settings2 = settings.model_copy(update={"topic_positions": topic2})

    async def settle():
        await asyncio.sleep(settings.reorder_window_s + 10)

    await _run_services(settings2, settle)
    with psycopg.connect(DB) as c:
        assert c.execute(
            "SELECT count(*) FROM vehicle_positions WHERE vehicle_id = %s", (vid,)
        ).fetchone()[0] == len(clean)
        assert c.execute(ARR_SQL, (trip_id, vid)).fetchone()[0] == len(stops)

    # Agregação incremental: o continuous aggregate vê as chegadas.
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("CALL refresh_continuous_aggregate('delay_hourly', NULL, NULL)")
        n, avg = c.execute(
            "SELECT sum(n), sum(avg_delay_s * n) / sum(n) FROM delay_hourly WHERE line_id = 'TEST'"
        ).fetchone()
    assert n >= len(stops) and round(avg) == DELAY

    with TestClient(create_app(settings, with_background=False)) as client:
        r = client.get("/api/analytics/stops", params={"line_id": "TEST", "days": 60})
        assert r.status_code == 200
        heat = client.get("/api/analytics/heatmap", params={"line_id": "TEST", "days": 3650})
        assert heat.status_code == 200
        assert sum(c["n"] for c in heat.json()) >= len(stops)
        assert client.get("/api/stats").status_code == 200

    _cleanup(trip_id)


def test_service_date_is_real_date():
    _require_infra()
    _, d, _ = _pick_trip()
    assert isinstance(d, date)
