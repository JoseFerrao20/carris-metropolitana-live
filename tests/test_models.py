import pytest
from hypothesis import given
from hypothesis import strategies as st

from cmlive.models import (
    RejectReason,
    VehiclePosition,
    normalize_timestamp,
    normalize_trip_id,
    parse_vehicle,
)

from .conftest import make_raw

NOW = 1_729_621_830.0


@pytest.mark.parametrize(
    "raw,expected",
    [
        (1729621800, 1729621800),  # segundos (exemplo do README oficial)
        (1729621800000, 1729621800),  # milissegundos (código atual da API)
        ("1729621800", 1729621800),
        (1729621800123, 1729621800),
        (None, None),
        (0, None),
        (-5, None),
        ("abc", None),
        (True, None),
        (float("nan"), None),
    ],
)
def test_normalize_timestamp(raw, expected):
    assert normalize_timestamp(raw) == expected


@given(st.integers(min_value=1_500_000_000, max_value=2_500_000_000))
def test_seconds_and_millis_agree(sec):
    assert normalize_timestamp(sec) == normalize_timestamp(sec * 1000) == sec


def test_normalize_trip_id_keeps_plan_and_agency_prefix():
    # Formato real (tempo real e GTFS coincidem só com o id completo)
    real = "[7DQC0][LA77N]1252_0_3_1700_1729_0_1"
    assert normalize_trip_id(real) == real
    assert (
        normalize_trip_id(" [FBZQZ][A2L1N]4001_0_3|1000|0710 ")
        == "[FBZQZ][A2L1N]4001_0_3|1000|0710"
    )
    assert normalize_trip_id("") is None
    assert normalize_trip_id(None) is None


def test_parse_official_example(example_vehicle):
    pos, reason = parse_vehicle(example_vehicle, collected_at=NOW)
    assert reason is None
    assert pos.vehicle_id == "41|1160"
    assert pos.ts == 1729621800
    assert pos.trip_id == "1503_0_2_1700_1729_0_2_21NBI"
    assert pos.stop_id == "030558"
    assert pos.current_status == "INCOMING_AT"


def test_parse_accepts_millis_like_production(example_vehicle):
    example_vehicle["timestamp"] = 1729621800 * 1000
    pos, _ = parse_vehicle(example_vehicle, collected_at=NOW)
    assert pos.ts == 1729621800


@pytest.mark.parametrize(
    "override,reason",
    [
        ({"id": None}, RejectReason.NO_ID),
        ({"timestamp": None}, RejectReason.BAD_TS),
        ({"lat": 0, "lon": 0}, RejectReason.BAD_COORDS),
        ({"lat": -9.2, "lon": 38.7}, RejectReason.BAD_COORDS),  # coordenadas trocadas
        ({"lat": None}, RejectReason.BAD_COORDS),
        ({"timestamp": int(NOW) - 3600}, RejectReason.STALE),
        ({"timestamp": int(NOW) + 3600}, RejectReason.FUTURE),
    ],
)
def test_parse_rejections(override, reason):
    pos, r = parse_vehicle(make_raw(**override), collected_at=NOW)
    assert pos is None and r == reason


def test_null_optional_fields_are_tolerated():
    pos, _ = parse_vehicle(
        make_raw(bearing=None, speed=None, trip_id=None, current_status="WEIRD"),
        collected_at=NOW,
    )
    assert pos.bearing is None and pos.trip_id is None and pos.current_status is None


def test_json_roundtrip():
    pos, _ = parse_vehicle(make_raw(), collected_at=NOW)
    assert VehiclePosition.from_json(pos.to_json()) == pos


def test_parse_real_live_payload():
    """Amostra real de /v2/vehicles recolhida a 2026-11-04 (timestamp em ms, ids com prefixo)."""
    import json
    from pathlib import Path

    items = json.loads(
        (Path(__file__).parent / "fixtures" / "vehicles_live_sample.json").read_text()
    )
    for raw in items:
        collected = raw["timestamp"] / 1000 + 60
        pos, reason = parse_vehicle(raw, collected_at=collected)
        assert reason is None
        assert pos.ts == raw["timestamp"] // 1000
        assert pos.trip_id == raw["trip_id"] and pos.trip_id.startswith("[")
        assert pos.vehicle_id == raw["id"]


def test_unavailable_stop_sentinel_becomes_none():
    pos, _ = parse_vehicle(make_raw(stop_id="UNAVAILABLE_STOP_ID"), collected_at=NOW)
    assert pos.stop_id is None
