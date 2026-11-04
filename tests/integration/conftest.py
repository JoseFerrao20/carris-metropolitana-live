import os
import zipfile
from pathlib import Path

import psycopg
import pytest

DB = os.environ.get("CMLIVE_DATABASE_URL", "postgresql://cmlive:cmlive@localhost:5432/cmlive")
MINI = Path(__file__).parent.parent / "fixtures" / "mini_gtfs"


@pytest.fixture(scope="session", autouse=True)
def gtfs_loaded(tmp_path_factory):
    """Na CI (BD vazia) carrega o mini-GTFS de fixture. Nunca substitui um GTFS já carregado."""
    try:
        conn = psycopg.connect(DB, connect_timeout=3)
    except psycopg.OperationalError:
        return  # os testes fazem skip
    with conn:
        if conn.execute("SELECT to_regclass('gtfs.stop_times')").fetchone()[0] is not None:
            return
        import asyncio

        from cmlive.db.repo import apply_schema
        from cmlive.gtfs_loader import load_zip

        async def schema():
            async with await psycopg.AsyncConnection.connect(DB) as c:
                await apply_schema(c)

        asyncio.run(schema())
        zpath = tmp_path_factory.mktemp("gtfs") / "mini.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            for f in MINI.glob("*.txt"):
                z.write(f, f.name)
        load_zip(conn, zpath, "fixture")
