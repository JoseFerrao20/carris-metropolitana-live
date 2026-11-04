import random

from hypothesis import given, settings
from hypothesis import strategies as st

from cmlive.delay import ArrivalDetector, ReorderBuffer, VehicleTracker, haversine_m
from cmlive.models import VehiclePosition

T0 = 1_718_000_000
TRIP = "1001_0_1_0600_0629_0_1_V5YX8"


def P(ts, stop, status="IN_TRANSIT_TO", trip=TRIP, vid="41|1", lat=38.7, lon=-9.2, collected=None):
    return VehiclePosition(
        vehicle_id=vid,
        ts=ts,
        lat=lat,
        lon=lon,
        bearing=None,
        speed=None,
        trip_id=trip,
        line_id="1001",
        route_id="1001_0",
        stop_id=stop,
        current_status=status,
        agency_id="41",
        collected_at=collected if collected is not None else ts + 5,
    )


def run(events):
    tr = VehicleTracker("41|1")
    return [a for e in events for a in tr.update(e)]


def test_haversine_known_distance():
    # 1° de latitude ≈ 111,195 km (R = 6371 km)
    assert abs(haversine_m(38.0, -9.0, 39.0, -9.0) - 111_195) < 1
    assert haversine_m(38.7, -9.2, 38.7, -9.2) == 0


def test_stopped_at_emits_midpoint():
    arr = run(
        [P(T0, "A", "INCOMING_AT"), P(T0 + 20, "A", "STOPPED_AT"), P(T0 + 40, "A", "STOPPED_AT")]
    )
    assert len(arr) == 1
    assert arr[0].stop_id == "A" and arr[0].method == "stopped"
    assert arr[0].observed_ts == T0 + 10 and arr[0].uncertainty_s == 10


def test_passed_without_stopping():
    arr = run([P(T0, "A", "INCOMING_AT"), P(T0 + 30, "B", "IN_TRANSIT_TO")])
    assert [(a.stop_id, a.method, a.observed_ts) for a in arr] == [("A", "passed", T0 + 15)]


def test_no_double_emission_after_stopping_then_leaving():
    arr = run(
        [
            P(T0, "A", "INCOMING_AT"),
            P(T0 + 20, "A", "STOPPED_AT"),
            P(T0 + 40, "B", "IN_TRANSIT_TO"),
            P(T0 + 60, "B", "STOPPED_AT"),
        ]
    )
    assert [a.stop_id for a in arr] == ["A", "B"]


def test_terminal_first_seen_stopped_emits_departure():
    arr = run([P(T0, "A", "STOPPED_AT"), P(T0 + 20, "A", "STOPPED_AT"), P(T0 + 40, "B")])
    assert [(a.stop_id, a.method, a.observed_ts) for a in arr] == [("A", "departed", T0 + 30)]


def test_trip_change_resets_state():
    arr = run(
        [
            P(T0, "A", "STOPPED_AT", trip="t1"),
            P(T0 + 20, "B", trip="t1"),
            P(T0 + 40, "A", "INCOMING_AT", trip="t2"),
            P(T0 + 60, "A", "STOPPED_AT", trip="t2"),
        ]
    )
    assert [(a.trip_id, a.stop_id) for a in arr] == [("t1", "A"), ("t2", "A")]


def test_large_gap_is_not_trusted():
    tr = VehicleTracker("41|1", max_gap_s=120)
    arr = [a for e in [P(T0, "A", "INCOMING_AT"), P(T0 + 600, "C")] for a in tr.update(e)]
    assert arr == [] and tr.skipped_gap == 1


def test_geofence():
    coords = {"A": (38.7, -9.2)}
    tr = VehicleTracker("41|1", stop_coords=coords.get, geofence_m=40)
    arr = [a for e in [P(T0, "A", lat=38.71), P(T0 + 10, "A", lat=38.7002)] for a in tr.update(e)]
    assert [(a.stop_id, a.method) for a in arr] == [("A", "geofence")]


def test_no_trip_no_arrivals():
    assert run([P(T0, "A", "STOPPED_AT", trip=None), P(T0 + 20, "B", trip=None)]) == []


# ------------------------------------------------------------------ reordenação


def test_reorder_buffer_sorts_within_window():
    b = ReorderBuffer(window_s=30)
    for t in (T0 + 20, T0, T0 + 10):
        b.push(P(t, "A", collected=T0 + 100))
    assert [p.ts for p in b.pop_ready(now=T0)] == []  # ainda dentro da janela
    assert [p.ts for p in b.drain()] == [T0, T0 + 10, T0 + 20]


def test_reorder_buffer_late_and_duplicate():
    b = ReorderBuffer(window_s=10)
    b.push(P(T0, "A"))
    b.push(P(T0, "A"))  # duplicado no buffer
    b.pop_ready(now=T0 + 100)
    assert not b.push(P(T0, "A"))  # duplicado já libertado
    assert not b.push(P(T0 - 5, "A"))  # tarde demais
    assert (b.duplicates, b.late) == (2, 1)


def test_watermark_releases_by_event_time():
    b = ReorderBuffer(window_s=10)
    b.push(P(T0, "A", collected=10**12))
    b.push(P(T0 + 11, "A", collected=10**12))
    assert [p.ts for p in b.pop_ready(now=0)] == [T0]


TRAJECTORY = [
    P(T0, "A", "INCOMING_AT"),
    P(T0 + 10, "A", "STOPPED_AT"),
    P(T0 + 20, "B"),
    P(T0 + 30, "B", "INCOMING_AT"),
    P(T0 + 40, "C"),
    P(T0 + 50, "C", "STOPPED_AT"),
    P(T0 + 60, "D"),
    P(T0 + 70, "D", "STOPPED_AT"),
]


def detect(events, window=1000):
    d = ArrivalDetector(window_s=window)
    for e in events:
        d.push(e)
    return [(a.stop_id, a.observed_ts, a.method) for a in d.flush()]


@settings(max_examples=300)
@given(
    st.randoms(use_true_random=False), st.lists(st.integers(0, len(TRAJECTORY) - 1), max_size=10)
)
def test_detection_invariant_to_shuffle_and_duplicates(rnd: random.Random, dup_idx):
    """Com janela suficiente, duplicados e qualquer ordem dão o mesmo resultado."""
    expected = detect(TRAJECTORY)
    noisy = TRAJECTORY + [TRAJECTORY[i] for i in dup_idx]
    rnd.shuffle(noisy)
    assert detect(noisy) == expected
    assert [s for s, *_ in expected] == ["A", "B", "C", "D"]


def test_first_observation_inside_geofence_is_not_an_arrival():
    """Ao arrancar o serviço, um veículo já junto à paragem não tem chegada medível."""
    coords = {"A": (38.7, -9.2)}
    tr = VehicleTracker("41|1", stop_coords=coords.get, geofence_m=40)
    evs = [
        P(T0, "A", "INCOMING_AT", lat=38.7001),
        P(T0 + 20, "A", "INCOMING_AT", lat=38.7001),
        P(T0 + 40, "B", lat=38.71),
    ]
    arr = [a for e in evs for a in tr.update(e)]
    assert [(a.stop_id, a.method, a.observed_ts) for a in arr] == [("A", "departed", T0 + 30)]


def test_missing_stop_id_is_not_evidence_of_passing():
    arr = run([P(T0, "A", "INCOMING_AT"), P(T0 + 20, None), P(T0 + 40, "A", "STOPPED_AT")])
    assert [(a.stop_id, a.method) for a in arr] == [("A", "stopped")]
