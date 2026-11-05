"""Ponto de entrada: ``python -m cmlive <serviço>``."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import logging
import signal
from pathlib import Path

import orjson

from .config import get_settings


def _stop_event() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    return stop


def _metrics(port: int) -> None:
    if port:
        from prometheus_client import start_http_server

        start_http_server(port)


async def collector(args) -> None:
    import httpx

    from .bus import KafkaProducer
    from .collector import Collector, NdjsonRecorder
    from .source import CircuitBreaker, VehicleSource

    s = get_settings()
    _metrics(args.metrics_port)
    producer = KafkaProducer(s.kafka_bootstrap)
    await producer.start()
    async with httpx.AsyncClient(
        timeout=s.http_timeout_s, headers={"user-agent": "cmlive/0.1 (portfolio project)"}
    ) as client:
        src = VehicleSource(
            client,
            s.api_base_url,
            max_retries=s.max_retries,
            breaker=CircuitBreaker(s.breaker_failure_threshold, s.breaker_reset_s),
        )
        rec = NdjsonRecorder(s.record_dir) if s.record_dir else None
        c = Collector(src, producer, s.topic_positions, stale_after_s=s.stale_after_s, recorder=rec)
        try:
            await c.run(s.poll_interval_s, _stop_event())
        finally:
            await producer.stop()


async def replay(args) -> None:
    """Volta a publicar respostas gravadas (NDJSON gzip), ao ritmo original ou acelerado."""
    from .bus import KafkaProducer
    from .collector import Collector

    s = get_settings()
    producer = KafkaProducer(s.kafka_bootstrap)
    await producer.start()
    c = Collector(source=None, producer=producer, topic=s.topic_positions, stale_after_s=10**9)
    prev = None
    try:
        for f in sorted(Path(args.directory).glob("*.ndjson.gz")):
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    rec = orjson.loads(line)
                    if prev is not None and args.speed > 0:
                        await asyncio.sleep(max(0, rec["collected_at"] - prev) / args.speed)
                    prev = rec["collected_at"]
                    r = await c.process(rec["vehicles"], rec["collected_at"])
                    logging.info("replay %s: %d novos", f.name, r.emitted)
    finally:
        await producer.stop()


async def ingestor(args) -> None:
    from .services import run_ingestor

    _metrics(args.metrics_port)
    await run_ingestor(get_settings(), _stop_event())


async def delay_engine(args) -> None:
    from .bus import KafkaProducer
    from .services import run_delay_engine

    s = get_settings()
    _metrics(args.metrics_port)
    producer = KafkaProducer(s.kafka_bootstrap)
    await producer.start()
    try:
        await run_delay_engine(s, _stop_event(), producer)
    finally:
        await producer.stop()


def gtfs(args) -> None:
    from .gtfs_loader import refresh

    s = get_settings()
    print(refresh(s.database_url, s.gtfs_urls, args.zip or None, force=args.force))


def export(args) -> None:
    """Exporta posições e chegadas para Parquet via DuckDB (extensão postgres)."""
    import duckdb

    s = get_settings()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute(f"ATTACH '{s.database_url}' AS pg (TYPE postgres, READ_ONLY)")
    since = f"now() - INTERVAL '{int(args.days)} days'"
    for name, sql in {
        "stop_arrivals": f"SELECT * FROM pg.public.stop_arrivals WHERE scheduled_at > {since}",
        "vehicle_positions": f"SELECT * FROM pg.public.vehicle_positions WHERE ts > {since}",
        "delay_hourly": "SELECT * FROM pg.public.delay_hourly",
    }.items():
        path = out / f"{name}.parquet"
        con.execute(f"COPY ({sql}) TO '{path}' (FORMAT parquet, COMPRESSION zstd)")
        print(path, con.execute(f"SELECT count(*) FROM '{path}'").fetchone()[0], "linhas")


async def validate(args) -> None:
    """Compara as nossas chegadas de hoje com o observed_arrival oficial (/v2/arrivals/by_stop)."""
    import httpx
    import psycopg

    from .validate import compare, fetch_official, summarize

    s = get_settings()
    async with await psycopg.AsyncConnection.connect(s.database_url) as conn:
        # O endpoint oficial usa os ids ANTIGOS das paragens (legacy_ids do GTFS).
        cur = await conn.execute(
            """SELECT a.stop_id, coalesce(split_part(s.legacy_ids, '|', 1), a.stop_id)
               FROM stop_arrivals a LEFT JOIN gtfs.stops s USING (stop_id)
               WHERE a.service_date = current_date
               GROUP BY 1, 2 ORDER BY count(*) DESC LIMIT %s""",
            (args.stops,),
        )
        stops = await cur.fetchall()
        rows, official_total = [], 0
        async with httpx.AsyncClient(timeout=s.http_timeout_s) as client:
            for stop_id, api_stop_id in stops:
                cur = await conn.execute(
                    """SELECT trip_id, extract(epoch FROM observed_at)::float8 FROM stop_arrivals
                       WHERE stop_id = %s AND service_date = current_date""",
                    (stop_id,),
                )
                ours = dict(await cur.fetchall())
                try:
                    official = await fetch_official(client, s.api_base_url, api_stop_id)
                except httpx.HTTPError as e:
                    logging.warning("paragem %s: %s", api_stop_id, e)
                    continue
                official_total += len(official)
                rows += compare(ours, official, stop_id)
    out = summarize(rows)
    out["stops_checked"] = len(stops)
    out["official_observed_arrivals"] = official_total
    if official_total == 0:
        out["note"] = "a API não publicou nenhum observed_arrival para estas paragens"
    print(orjson.dumps(out, option=orjson.OPT_INDENT_2).decode())


def report(args) -> None:
    from .report import build

    s = get_settings()
    print(build(s.database_url, s.timezone))


def web(args) -> None:
    import uvicorn

    from .web.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser(prog="cmlive")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("collector", "ingestor", "delay-engine"):
        sp = sub.add_parser(name)
        sp.add_argument("--metrics-port", type=int, default=9100)
    sp = sub.add_parser("replay")
    sp.add_argument("directory")
    sp.add_argument("--speed", type=float, default=10.0, help="0 = o mais rápido possível")
    sp = sub.add_parser("gtfs")
    sp.add_argument("--zip", help="ficheiro local em vez de descarregar")
    sp.add_argument("--force", action="store_true", help="recarrega mesmo sem alterações")
    sp = sub.add_parser("export")
    sp.add_argument("--days", type=int, default=7)
    sp.add_argument("--out", default="data/export")
    sp = sub.add_parser("validate")
    sp.add_argument("--stops", type=int, default=50)
    sub.add_parser("report", help="tabelas Markdown com os números do README")
    sp = sub.add_parser("web")
    sp.add_argument("--host", default="0.0.0.0")
    sp.add_argument("--port", type=int, default=8000)
    args = p.parse_args()

    if args.cmd == "gtfs":
        gtfs(args)
    elif args.cmd == "export":
        export(args)
    elif args.cmd == "report":
        report(args)
    elif args.cmd == "web":
        web(args)
    else:
        fn = {
            "collector": collector,
            "ingestor": ingestor,
            "delay-engine": delay_engine,
            "replay": replay,
            "validate": validate,
        }[args.cmd]
        asyncio.run(fn(args))


if __name__ == "__main__":
    main()
