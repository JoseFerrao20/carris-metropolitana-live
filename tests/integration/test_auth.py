"""Autenticação e favoritas contra Postgres real (``make up-infra``)."""

import asyncio
import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from cmlive.config import Settings
from cmlive.db.repo import apply_schema
from cmlive.web.app import create_app
from cmlive.web.auth import COOKIE, token_hash

pytestmark = pytest.mark.integration

DB = os.environ.get("CMLIVE_DATABASE_URL", "postgresql://cmlive:cmlive@localhost:5432/cmlive")
PW = "password-de-teste-123"


@pytest.fixture(scope="module", autouse=True)
def schema():
    try:
        psycopg.connect(DB, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("Postgres indisponível (make up-infra)")

    async def go():
        async with await psycopg.AsyncConnection.connect(DB) as c:
            await apply_schema(c)

    asyncio.run(go())


@pytest.fixture
def client():
    app = create_app(Settings(database_url=DB, frontend_dist="/nao-existe"), with_background=False)
    with TestClient(app) as c:
        yield c


def email() -> str:
    return f"teste-{uuid.uuid4().hex[:10]}@exemplo.pt"


def test_register_sets_secure_session_cookie_and_me_works(client):
    e = email()
    r = client.post("/api/auth/register", json={"email": e, "password": PW})
    assert r.status_code == 201 and r.json()["email"] == e
    cookie = r.headers["set-cookie"]
    assert f"{COOKIE}=" in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert client.get("/api/auth/me").json()["email"] == e


def test_session_token_is_stored_only_as_hash(client):
    client.post("/api/auth/register", json={"email": email(), "password": PW})
    token = client.cookies[COOKIE]
    with psycopg.connect(DB) as c:
        assert c.execute(
            "SELECT 1 FROM sessions WHERE token_hash = %s", (token_hash(token),)
        ).fetchone()
        assert not c.execute(
            "SELECT 1 FROM sessions WHERE encode(token_hash, 'escape') LIKE %s", (f"%{token}%",)
        ).fetchone()


def test_duplicate_email_is_case_insensitive(client):
    e = email()
    assert client.post("/api/auth/register", json={"email": e, "password": PW}).status_code == 201
    r = client.post("/api/auth/register", json={"email": e.upper(), "password": PW})
    assert r.status_code == 409


def test_invalid_registration_is_rejected(client):
    r = client.post("/api/auth/register", json={"email": "invalido", "password": "curta"})
    assert r.status_code == 422
    assert "Email inválido" in r.json()["detail"] and "entre 10 e 128" in r.json()["detail"]


def test_logout_revokes_the_session_server_side(client):
    client.post("/api/auth/register", json={"email": email(), "password": PW})
    stolen = client.cookies[COOKIE]
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    # Mesmo que alguém tenha copiado o cookie, depois do logout já não serve.
    client.cookies.set(COOKIE, stolen)
    assert client.get("/api/auth/me").status_code == 401


def test_login_does_not_reveal_whether_the_account_exists(client):
    e = email()
    client.post("/api/auth/register", json={"email": e, "password": PW})
    client.post("/api/auth/logout")
    wrong_pw = client.post("/api/auth/login", json={"email": e, "password": "errada-errada"})
    no_user = client.post("/api/auth/login", json={"email": email(), "password": PW})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()
    ok = client.post("/api/auth/login", json={"email": e.upper(), "password": PW})
    assert ok.status_code == 200 and client.get("/api/auth/me").status_code == 200


def test_brute_force_is_throttled(client):
    e = email()
    client.post("/api/auth/register", json={"email": e, "password": PW})
    client.post("/api/auth/logout")
    codes = [
        client.post("/api/auth/login", json={"email": e, "password": "errada-errada"}).status_code
        for _ in range(6)
    ]
    assert codes == [401] * 5 + [429]
    # Bloqueado mesmo com a password certa, até a janela passar.
    assert client.post("/api/auth/login", json={"email": e, "password": PW}).status_code == 429


def test_cross_site_requests_are_refused(client):
    client.post("/api/auth/register", json={"email": email(), "password": PW})
    r = client.put("/api/me/favorites/1717", headers={"origin": "https://mau.exemplo"})
    assert r.status_code == 403
    assert client.get("/api/me/favorites").json() == []


def test_favorites_are_private_idempotent_and_validated(client):
    client.post("/api/auth/register", json={"email": email(), "password": PW})
    assert client.put("/api/me/favorites/1717").status_code == 204
    assert client.put("/api/me/favorites/1717").status_code == 204  # idempotente
    assert client.put("/api/me/favorites/4512").status_code == 204
    assert client.get("/api/me/favorites").json() == ["1717", "4512"]
    assert client.put("/api/me/favorites/x;DROP").status_code == 422
    assert client.delete("/api/me/favorites/1717").status_code == 204
    assert client.get("/api/me/favorites").json() == ["4512"]

    # Outro utilizador não vê nem mexe nas favoritas do primeiro.
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": email(), "password": PW})
    assert client.get("/api/me/favorites").json() == []


def test_favorites_require_a_session(client):
    client.cookies.clear()
    assert client.get("/api/me/favorites").status_code == 401
    assert client.put("/api/me/favorites/1717").status_code == 401
    client.cookies.set(COOKIE, "token-inventado")
    assert client.get("/api/auth/me").status_code == 401
