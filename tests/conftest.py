import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def example_vehicle() -> dict:
    """Primeiro elemento do exemplo oficial de /v2/vehicles (README da API da CM)."""
    return json.loads((FIXTURES / "vehicles_example.json").read_text())[0]


def make_raw(vid: str = "41|1160", ts: int = 1_729_621_800, **kw) -> dict:
    base = {
        "id": vid,
        "timestamp": ts,
        "lat": 38.73644,
        "lon": -9.21281,
        "bearing": 0,
        "speed": 0,
        "trip_id": "1503_0_2_1700_1729_0_2_21NBI",
        "line_id": "1503",
        "route_id": "1503_0",
        "stop_id": "030558",
        "current_status": "INCOMING_AT",
        "agency_id": "41",
    }
    base.update(kw)
    return base
