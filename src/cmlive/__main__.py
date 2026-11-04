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
    print(refresh(s.database_url, s.gtfs_urls, args.zip or None))


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
    sp = sub.add_parser("web")
    sp.add_argument("--host", default="0.0.0.0")
    sp.add_argument("--port", type=int, default=8000)
    args = p.parse_args()

    if args.cmd == "gtfs":
        gtfs(args)
    elif args.cmd == "web":
        web(args)
    else:
        fn = {
            "collector": collector,
            "ingestor": ingestor,
            "delay-engine": delay_engine,
            "replay": replay,
        }[args.cmd]
        asyncio.run(fn(args))


if __name__ == "__main__":
    main()
