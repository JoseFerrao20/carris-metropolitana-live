from hypothesis import given, settings
from hypothesis import strategies as st

from cmlive.bus import MemoryBus
from cmlive.collector import Collector, Deduplicator
from cmlive.models import VehiclePosition, parse_vehicle
from cmlive.source import SourceUnavailable

from .conftest import make_raw

NOW = 1_729_621_900.0
TOPIC = "vehicle-positions"


class FakeSource:
    def __init__(self, responses):
        self.responses = list(responses)

    async def fetch(self):
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make_collector(responses):
    bus = MemoryBus()
    return Collector(FakeSource(responses), bus, TOPIC, clock=lambda: NOW), bus


async def test_repeated_responses_are_deduplicated():
    resp = [make_raw("41|1", 1_729_621_800), make_raw("41|2", 1_729_621_810)]
    c, bus = make_collector([resp, resp, resp])
    r1, r2, r3 = [await c.poll_once() for _ in range(3)]
    assert (r1.emitted, r2.emitted, r3.emitted) == (2, 0, 0)
    assert r2.duplicates == 2
    assert len(bus.all(TOPIC)) == 2


async def test_only_advanced_vehicles_emitted():
    c, _bus = make_collector(
        [
            [make_raw("41|1", 1_729_621_800), make_raw("41|2", 1_729_621_800)],
            [make_raw("41|1", 1_729_621_820), make_raw("41|2", 1_729_621_800)],
        ]
    )
    await c.poll_once()
    r = await c.poll_once()
    assert r.emitted == 1


async def test_stale_cache_regression_ignored():
    c, _bus = make_collector(
        [
            [make_raw("41|1", 1_729_621_820)],
            [make_raw("41|1", 1_729_621_800)],  # nó de cache mais velho
        ]
    )
    await c.poll_once()
    r = await c.poll_once()
    assert r.emitted == 0 and r.duplicates == 1


async def test_key_is_vehicle_id_so_order_is_per_vehicle():
    c, bus = make_collector([[make_raw("41|1", 1_729_621_800)], [make_raw("41|1", 1_729_621_830)]])
    await c.poll_once()
    await c.poll_once()
    recs = bus.all(TOPIC)
    assert {r.partition for r in recs} == {recs[0].partition}
    assert [VehiclePosition.from_json(r.value).ts for r in recs] == [1_729_621_800, 1_729_621_830]


async def test_source_down_does_not_crash_and_resumes():
    c, _bus = make_collector(
        [
            SourceUnavailable("503"),
            [make_raw("41|1", 1_729_621_800)],
        ]
    )
    r1 = await c.poll_once()
    r2 = await c.poll_once()
    assert r1.error and r2.emitted == 1


async def test_invalid_items_counted_not_fatal():
    c, _ = make_collector([[make_raw(), "lixo", make_raw("41|9", lat=0, lon=0)]])
    r = await c.poll_once()
    assert (r.emitted, r.rejected) == (1, 2)


@settings(max_examples=200)
@given(st.lists(st.tuples(st.sampled_from(["a", "b", "c"]), st.integers(0, 50)), max_size=60))
def test_dedup_emits_strictly_increasing_ts_per_vehicle(events):
    d = Deduplicator()
    last: dict[str, int] = {}
    for vid, dt in events:
        pos, _ = parse_vehicle(make_raw(vid, 1_729_621_800 + dt), collected_at=NOW)
        if d.is_new(pos):
            assert pos.ts > last.get(vid, -1)
            last[vid] = pos.ts
    # O último emitido por veículo é o máximo visto.
    for vid in last:
        assert last[vid] == max(dt for v, dt in events if v == vid) + 1_729_621_800
