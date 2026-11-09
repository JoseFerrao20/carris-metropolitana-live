"""O FastAPI serve o build do frontend React (sem precisar de BD nem de Kafka)."""

from fastapi.testclient import TestClient

from cmlive.config import Settings
from cmlive.web.app import create_app

# Porta sem nada à escuta: a pool abre em segundo plano e não bloqueia o teste.
DB = "postgresql://x:x@127.0.0.1:1/x?connect_timeout=1"


def client(dist: str) -> TestClient:
    return TestClient(
        create_app(Settings(database_url=DB, frontend_dist=dist), with_background=False)
    )


def test_serves_spa_routes_and_hashed_assets(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(
        '<div id="root"></div><script src="/assets/app-abc123.js">'
    )
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)")
    with client(str(tmp_path)) as c:
        for path in ("/", "/analytics", "/entrar"):
            r = c.get(path)
            assert r.status_code == 200 and 'id="root"' in r.text
            assert r.headers["cache-control"] == "no-cache"
            assert c.head(path).status_code == 200  # monitores de disponibilidade usam HEAD
        a = c.get("/assets/app-abc123.js")
        assert a.status_code == 200
        assert "immutable" in a.headers["cache-control"]
        assert c.get("/assets/nao-existe.js").status_code == 404


def test_explains_missing_build(tmp_path):
    with client(str(tmp_path / "vazio")) as c:
        r = c.get("/")
        assert r.status_code == 503
        assert "npm run build" in r.text


def test_starts_and_serves_ui_with_database_down(tmp_path):
    """Regressão: o warm start bloqueava o arranque ~30 s quando a BD estava em baixo."""
    import time

    (tmp_path / "index.html").write_text("ok")
    t = time.monotonic()
    app = create_app(
        Settings(database_url=DB, frontend_dist=str(tmp_path), kafka_bootstrap="127.0.0.1:1")
    )
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
    assert time.monotonic() - t < 5
