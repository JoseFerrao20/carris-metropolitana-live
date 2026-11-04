import httpx
import pytest
import respx

from cmlive.source import (
    BreakerOpen,
    BreakerState,
    CircuitBreaker,
    SourceUnavailable,
    VehicleSource,
)

URL = "https://api.test/v2/vehicles"


async def _nosleep(_):
    return None


def make_source(**kw) -> VehicleSource:
    return VehicleSource(httpx.AsyncClient(), "https://api.test/v2", sleep=_nosleep, **kw)


@respx.mock
async def test_success():
    respx.get(URL).respond(200, json=[{"id": "1"}])
    assert await make_source().fetch() == [{"id": "1"}]


@respx.mock
async def test_retries_then_succeeds():
    route = respx.get(URL)
    route.side_effect = [
        httpx.Response(503),
        httpx.ConnectTimeout("t"),
        httpx.Response(200, json=[{"id": "1"}]),
    ]
    src = make_source(max_retries=3)
    assert await src.fetch() == [{"id": "1"}]
    assert route.call_count == 3
    assert src.breaker.failures == 0


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, json=[]),  # comportamento real com a cache vazia
        httpx.Response(500),
        httpx.Response(200, content=b"<html>"),
        httpx.Response(200, json={"error": "x"}),
        httpx.Response(200, json=[]),
    ],
)
async def test_unusable_responses_raise(response):
    respx.get(URL).mock(return_value=response)
    with pytest.raises(SourceUnavailable):
        await make_source(max_retries=1).fetch()


@respx.mock
async def test_breaker_opens_and_recovers():
    t = [0.0]
    breaker = CircuitBreaker(threshold=2, reset_s=30, clock=lambda: t[0])
    route = respx.get(URL).respond(503)
    src = make_source(max_retries=0, breaker=breaker)

    for _ in range(2):
        with pytest.raises(SourceUnavailable):
            await src.fetch()
    assert breaker.state is BreakerState.OPEN

    calls = route.call_count
    with pytest.raises(BreakerOpen):
        await src.fetch()
    assert route.call_count == calls  # nem tentou

    t[0] = 31
    route.respond(200, json=[{"id": "1"}])
    assert await src.fetch() == [{"id": "1"}]
    assert breaker.state is BreakerState.CLOSED


def test_half_open_failure_reopens_immediately():
    t = [0.0]
    b = CircuitBreaker(threshold=3, reset_s=10, clock=lambda: t[0])
    for _ in range(3):
        b.record_failure()
    t[0] = 11
    assert b.allow() and b.state is BreakerState.HALF_OPEN
    b.record_failure()
    assert b.state is BreakerState.OPEN
