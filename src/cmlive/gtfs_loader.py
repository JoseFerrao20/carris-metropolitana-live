"""Carrega o GTFS da Carris Metropolitana para o Postgres com troca atómica de esquema.

O feed real tem cerca de 8 milhões de linhas em ``stop_times.txt`` (~530 MB descomprimido),
por isso tudo é feito em streaming: zip → csv → COPY, sem materializar em memória.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import tempfile
import time
import zipfile
from collections.abc import Iterable, Iterator
from datetime import date, datetime, timedelta
from importlib import resources
from pathlib import Path

import httpx
import psycopg

from .gtfs_time import parse_gtfs_time

log = logging.getLogger(__name__)

STAGING = "gtfs_staging"


def download(urls: Iterable[str], dest: Path, timeout: float = 120.0) -> str:
    """Tenta cada URL por ordem; devolve o que funcionou."""
    errors = []
    for url in urls:
        try:
            with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as r:
                r.raise_for_status()
                with dest.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            if not zipfile.is_zipfile(dest):
                raise ValueError("resposta não é um ZIP")
            return url
        except (httpx.HTTPError, ValueError) as e:
            errors.append(f"{url}: {e}")
            log.warning("falhou %s: %s", url, e)
    raise RuntimeError("nenhum URL de GTFS funcionou:\n" + "\n".join(errors))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    if name not in zf.namelist():
        return iter(())
    fh = io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline="")
    return csv.DictReader(fh)


def _esc(v: object) -> str:
    """Escapa um valor para o formato *text* do COPY."""
    if v is None or v == "":
        return r"\N"
    s = str(v)
    if any(c in s for c in "\\\t\n\r"):
        s = s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
    return s


def _copy(cur: psycopg.Cursor, table: str, cols: list[str], rows: Iterable[tuple]) -> int:
    n = 0
    buf: list[str] = []
    with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
        for row in rows:
            buf.append("\t".join(_esc(v) for v in row))
            n += 1
            if len(buf) >= 50_000:
                cp.write("\n".join(buf) + "\n")
                buf.clear()
        if buf:
            cp.write("\n".join(buf) + "\n")
    return n


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y%m%d").date()


def _calendar_dates(zf: zipfile.ZipFile) -> Iterator[tuple]:
    # calendar.txt (opcional) expandido para datas; calendar_dates.txt aplica exceções por cima.
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for r in _rows(zf, "calendar.txt"):
        d, end = _parse_date(r["start_date"]), _parse_date(r["end_date"])
        while d <= end:
            if r.get(days[d.weekday()]) == "1":
                yield (r["service_id"], d, 1)
            d += timedelta(days=1)
    for r in _rows(zf, "calendar_dates.txt"):
        yield (r["service_id"], _parse_date(r["date"]), int(r["exception_type"]))


def load_zip(conn: psycopg.Connection, zip_path: Path, source_url: str = "") -> dict:
    t0 = time.monotonic()
    digest = sha256_file(zip_path)
    ddl = resources.files("cmlive.db").joinpath("gtfs_schema.sql").read_text()
    stats: dict[str, int | str | float] = {"sha256": digest}

    with zipfile.ZipFile(zip_path) as zf, conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {STAGING} CASCADE")
        cur.execute(ddl.format(schema=STAGING))

        stats["routes"] = _copy(
            cur,
            f"{STAGING}.routes",
            ["route_id", "line_id", "short_name", "long_name", "color", "text_color"],
            (
                (
                    r["route_id"],
                    r.get("line_id") or r.get("route_short_name"),
                    r.get("route_short_name"),
                    r.get("route_long_name"),
                    r.get("route_color"),
                    r.get("route_text_color"),
                )
                for r in _rows(zf, "routes.txt")
            ),
        )
        stats["stops"] = _copy(
            cur,
            f"{STAGING}.stops",
            ["stop_id", "name", "lat", "lon", "municipality", "legacy_ids"],
            (
                (
                    r["stop_id"],
                    r.get("stop_name"),
                    r.get("stop_lat"),
                    r.get("stop_lon"),
                    r.get("municipality_name"),
                    r.get("legacy_ids"),  # GTFS da TML: ids antigos que o tempo real ainda usa
                )
                for r in _rows(zf, "stops.txt")
            ),
        )
        stats["trips"] = _copy(
            cur,
            f"{STAGING}.trips",
            ["trip_id", "route_id", "service_id", "direction_id", "pattern_id", "headsign"],
            (
                (
                    r["trip_id"],
                    r["route_id"],
                    r["service_id"],
                    r.get("direction_id"),
                    r.get("pattern_id"),
                    r.get("trip_headsign"),
                )
                for r in _rows(zf, "trips.txt")
            ),
        )
        stats["calendar_dates"] = _copy(
            cur,
            f"{STAGING}.calendar_dates",
            ["service_id", "date", "exception_type"],
            _calendar_dates(zf),
        )
        stats["stop_times"] = _copy(
            cur,
            f"{STAGING}.stop_times",
            ["trip_id", "stop_sequence", "stop_id", "arrival_s"],
            (
                (
                    r["trip_id"],
                    r["stop_sequence"],
                    r["stop_id"],
                    parse_gtfs_time(r["arrival_time"] or r["departure_time"]),
                )
                for r in _rows(zf, "stop_times.txt")
                if (r.get("arrival_time") or r.get("departure_time"))
            ),
        )

        feed_version = (
            next((r.get("feed_version") for r in _rows(zf, "feed_info.txt")), None) or digest[:12]
        )
        stats["feed_version"] = feed_version

        log.info("COPY terminado em %.1fs; a criar índices", time.monotonic() - t0)
        cur.execute(f"""
            ALTER TABLE {STAGING}.stop_times ADD PRIMARY KEY (trip_id, stop_sequence);
            CREATE INDEX ON {STAGING}.calendar_dates (service_id, date);
            CREATE INDEX ON {STAGING}.trips (route_id);
            ANALYZE {STAGING}.stop_times;
            ANALYZE {STAGING}.trips;
        """)
        cur.execute(
            f"INSERT INTO {STAGING}.feed_info VALUES (%s, now(), %s, %s, %s, %s)",
            (feed_version, source_url, digest, stats["trips"], stats["stop_times"]),
        )

        # Troca atómica: os leitores veem o GTFS antigo até ao COMMIT, e depois o novo.
        cur.execute("DROP SCHEMA IF EXISTS gtfs CASCADE")
        cur.execute(f"ALTER SCHEMA {STAGING} RENAME TO gtfs")
    conn.commit()
    stats["seconds"] = round(time.monotonic() - t0, 1)
    log.info("GTFS carregado: %s", stats)
    return stats


def current_sha(conn: psycopg.Connection) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('gtfs.feed_info')")
        if cur.fetchone()[0] is None:
            return None
        cur.execute("SELECT sha256 FROM gtfs.feed_info ORDER BY loaded_at DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None


def refresh(
    database_url: str, urls: Iterable[str], zip_path: str | None = None, force: bool = False
) -> dict:
    """Descarrega (ou usa um ficheiro local) e carrega só se o conteúdo mudou."""
    with tempfile.TemporaryDirectory() as tmp, psycopg.connect(database_url) as conn:
        if zip_path:
            path, url = Path(zip_path), f"file://{zip_path}"
        else:
            path = Path(tmp) / "gtfs.zip"
            url = download(urls, path)
        if not force and current_sha(conn) == sha256_file(path):
            log.info("GTFS sem alterações (%s)", url)
            return {"unchanged": True}
        return load_zip(conn, path, url)
