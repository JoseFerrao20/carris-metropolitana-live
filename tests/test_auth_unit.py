from starlette.requests import Request

from cmlive.web.auth import (
    LoginLimiter,
    hash_password,
    new_token,
    same_origin,
    token_hash,
    validate_credentials,
    verify_password,
)


def test_password_hash_is_argon2id_and_verifies():
    h = hash_password("uma-password-longa")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "uma-password-longa")
    assert not verify_password(h, "outra-password")


def test_unknown_account_never_verifies_even_with_the_dummy_password():
    assert not verify_password(None, "password-ficticia-para-igualar-tempos")
    assert not verify_password("lixo-que-nao-e-hash", "x")


def test_tokens_are_random_and_only_the_hash_is_derived():
    t1, h1 = new_token()
    t2, _ = new_token()
    assert t1 != t2 and len(t1) >= 40
    assert h1 == token_hash(t1) and len(h1) == 32
    assert t1.encode() not in h1


def test_validate_credentials():
    assert validate_credentials("ana@exemplo.pt", "1234567890") == []
    assert validate_credentials("sem-arroba", "1234567890") == ["Email inválido."]
    assert "entre 10 e 128" in validate_credentials("ana@exemplo.pt", "curta")[0]
    assert validate_credentials("ana@exemplo.pt", "x" * 129)


def test_login_limiter_blocks_after_failures_and_resets():
    t = [0.0]
    lim = LoginLimiter(max_failures=3, window_s=60, clock=lambda: t[0])
    key = ("1.2.3.4", "ana@exemplo.pt")
    for _ in range(3):
        assert not lim.blocked(key)
        lim.failure(key)
    assert lim.blocked(key)
    assert not lim.blocked(("1.2.3.4", "outra@exemplo.pt"))  # por conta, não global
    t[0] = 61
    assert not lim.blocked(key)  # a janela passou
    lim.failure(key)
    lim.success(key)
    assert not lim.blocked(key)


def _req(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "headers": raw})


def test_same_origin():
    assert same_origin(_req({"host": "localhost:8000"}))  # sem Origin (curl/testes)
    assert same_origin(_req({"host": "localhost:8000", "origin": "http://localhost:8000"}))
    assert not same_origin(_req({"host": "localhost:8000", "origin": "https://mau.exemplo"}))
