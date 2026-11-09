"""Autenticação por sessão (cookie HttpOnly) e linhas favoritas por utilizador.

Decisões:
- **Sessões no servidor** (tabela ``sessions``), não JWT: o logout revoga mesmo a sessão.
  Na BD só fica o sha256 do token; o token em claro só existe no cookie do utilizador.
- **Argon2id** para as passwords, com o hash calculado numa thread (é pesado de propósito
  e não pode bloquear o event loop, que também serve o stream SSE do mapa).
- **CSRF:** cookie ``SameSite=Lax`` (o browser não o envia em POSTs vindos de outros sites)
  e, por precaução, os pedidos que alteram dados com ``Origin`` de outro site são recusados.
- **Enumeração de contas:** o login dá sempre a mesma mensagem e verifica um hash fictício
  quando o email não existe, para o tempo de resposta não revelar se a conta existe.
- **Força bruta:** limite de tentativas falhadas por IP + email.

Nota: este módulo NÃO usa ``from __future__ import annotations``. As dependências são
definidas dentro de ``build_router`` e o FastAPI precisa de ver os tipos já resolvidos
(com anotações em texto, procuraria ``require_user`` no espaço global e falharia).
"""

import hashlib
import re
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlsplit

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

COOKIE = "cmlive_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LINE_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
PASSWORD_MIN, PASSWORD_MAX = 10, 128

MSG_BAD_LOGIN = "Email ou password incorretos."
MSG_DUPLICATE = "Já existe uma conta com este email."
MSG_BAD_LINE = "Identificador de linha inválido."
MSG_THROTTLED = "Demasiadas tentativas. Tente novamente daqui a alguns minutos."

SQL_USER_BY_SESSION = """
    SELECT u.id, u.email FROM sessions s JOIN users u ON u.id = s.user_id
    WHERE s.token_hash = %s AND s.expires_at > now()"""
SQL_USER_BY_EMAIL = "SELECT id, email, password_hash FROM users WHERE lower(email) = lower(%s)"
SQL_INSERT_USER = "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id"
SQL_REHASH = "UPDATE users SET password_hash = %s WHERE id = %s"
SQL_INSERT_SESSION = "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)"
SQL_DELETE_SESSION = "DELETE FROM sessions WHERE token_hash = %s"
SQL_LIST_FAVORITES = "SELECT line_id FROM favorite_lines WHERE user_id = %s ORDER BY line_id"
SQL_ADD_FAVORITE = (
    "INSERT INTO favorite_lines (user_id, line_id) VALUES (%s, %s) ON CONFLICT DO NOTHING"
)
SQL_DEL_FAVORITE = "DELETE FROM favorite_lines WHERE user_id = %s AND line_id = %s"

_hasher = PasswordHasher()  # Argon2id com os parâmetros recomendados pela biblioteca
_DUMMY_HASH = _hasher.hash("password-ficticia-para-igualar-tempos")


# --------------------------------------------------------------------------- utilitários


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Verifica sempre um hash (o fictício se a conta não existir), para igualar tempos."""
    try:
        ok = _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return ok and password_hash is not None


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def new_token() -> tuple[str, bytes]:
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def validate_credentials(email: str, password: str) -> list[str]:
    errors = []
    if len(email) > 254 or not EMAIL_RE.match(email):
        errors.append("Email inválido.")
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        errors.append(f"A password tem de ter entre {PASSWORD_MIN} e {PASSWORD_MAX} caracteres.")
    return errors


class LoginLimiter:
    """No máximo ``max_failures`` tentativas falhadas por (IP, email) em ``window_s``."""

    def __init__(self, max_failures: int = 5, window_s: float = 900, clock=time.monotonic) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self.clock = clock
        self._failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def _recent(self, key: tuple[str, str]) -> deque[float]:
        q = self._failures[key]
        while q and self.clock() - q[0] > self.window_s:
            q.popleft()
        return q

    def blocked(self, key: tuple[str, str]) -> bool:
        return len(self._recent(key)) >= self.max_failures

    def failure(self, key: tuple[str, str]) -> None:
        self._recent(key).append(self.clock())

    def success(self, key: tuple[str, str]) -> None:
        self._failures.pop(key, None)


def same_origin(request: Request) -> bool:
    """Pedidos sem Origin (curl, testes) passam; com Origin, tem de ser o próprio host."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    return urlsplit(origin).netloc == request.headers.get("host")


# --------------------------------------------------------------------------- modelos


class Credentials(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str


@dataclass(frozen=True)
class AuthConfig:
    session_days: int = 30
    cookie_secure: bool = False  # True em produção (HTTPS)


# --------------------------------------------------------------------------- router


def build_router(config: AuthConfig, limiter: LoginLimiter | None = None) -> APIRouter:
    router = APIRouter(prefix="/api")
    limiter = limiter or LoginLimiter()

    def pool(request: Request):
        return request.app.state.pool

    async def csrf_guard(request: Request) -> None:
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not same_origin(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Origem não permitida.")

    async def current_user(request: Request) -> UserOut | None:
        token = request.cookies.get(COOKIE)
        if not token:
            return None
        async with pool(request).connection() as conn:
            cur = await conn.execute(SQL_USER_BY_SESSION, (token_hash(token),))
            row = await cur.fetchone()
        return UserOut(id=row[0], email=row[1]) if row else None

    async def require_user(user: Annotated[UserOut | None, Depends(current_user)]) -> UserOut:
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada.")
        return user

    User = Annotated[UserOut, Depends(require_user)]
    guarded = [Depends(csrf_guard)]

    async def start_session(conn: psycopg.AsyncConnection, user_id: int, resp: Response) -> None:
        token, digest = new_token()
        expires = datetime.now(UTC) + timedelta(days=config.session_days)
        await conn.execute("DELETE FROM sessions WHERE expires_at < now()")
        await conn.execute(SQL_INSERT_SESSION, (digest, user_id, expires))
        resp.set_cookie(
            COOKIE,
            token,
            max_age=config.session_days * 86400,
            httponly=True,
            secure=config.cookie_secure,
            samesite="lax",
            path="/",
        )

    def check_line(line_id: str) -> str:
        if not LINE_RE.match(line_id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, MSG_BAD_LINE)
        return line_id

    @router.post("/auth/register", status_code=201, response_model=UserOut, dependencies=guarded)
    async def register(body: Credentials, request: Request, response: Response):
        email = body.email.strip()
        if errors := validate_credentials(email, body.password):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, " ".join(errors))
        pw_hash = await run_in_threadpool(hash_password, body.password)
        async with pool(request).connection() as conn:
            try:
                cur = await conn.execute(SQL_INSERT_USER, (email, pw_hash))
            except psycopg.errors.UniqueViolation:
                raise HTTPException(status.HTTP_409_CONFLICT, MSG_DUPLICATE) from None
            user_id = (await cur.fetchone())[0]
            await start_session(conn, user_id, response)
        return UserOut(id=user_id, email=email)

    @router.post("/auth/login", response_model=UserOut, dependencies=guarded)
    async def login(body: Credentials, request: Request, response: Response):
        email = body.email.strip()
        key = (request.client.host if request.client else "?", email.lower())
        if limiter.blocked(key):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, MSG_THROTTLED)
        async with pool(request).connection() as conn:
            row = await (await conn.execute(SQL_USER_BY_EMAIL, (email,))).fetchone()
            ok = await run_in_threadpool(verify_password, row[2] if row else None, body.password)
            if not row or not ok:
                limiter.failure(key)
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, MSG_BAD_LOGIN)
            limiter.success(key)
            if _hasher.check_needs_rehash(row[2]):
                new_hash = await run_in_threadpool(hash_password, body.password)
                await conn.execute(SQL_REHASH, (new_hash, row[0]))
            await start_session(conn, row[0], response)
        return UserOut(id=row[0], email=row[1])

    @router.post("/auth/logout", status_code=204, dependencies=guarded)
    async def logout(request: Request, response: Response):
        token = request.cookies.get(COOKIE)
        if token:
            async with pool(request).connection() as conn:
                await conn.execute(SQL_DELETE_SESSION, (token_hash(token),))
        response.delete_cookie(
            COOKIE, path="/", samesite="lax", httponly=True, secure=config.cookie_secure
        )

    @router.get("/auth/me", response_model=UserOut)
    async def me(user: User):
        return user

    @router.get("/me/favorites", response_model=list[str])
    async def favorites(request: Request, user: User):
        async with pool(request).connection() as conn:
            cur = await conn.execute(SQL_LIST_FAVORITES, (user.id,))
            return [r[0] for r in await cur.fetchall()]

    @router.put("/me/favorites/{line_id}", status_code=204, dependencies=guarded)
    async def add_favorite(line_id: str, request: Request, user: User):
        async with pool(request).connection() as conn:
            await conn.execute(SQL_ADD_FAVORITE, (user.id, check_line(line_id)))

    @router.delete("/me/favorites/{line_id}", status_code=204, dependencies=guarded)
    async def remove_favorite(line_id: str, request: Request, user: User):
        async with pool(request).connection() as conn:
            await conn.execute(SQL_DEL_FAVORITE, (user.id, check_line(line_id)))

    return router
