import httpx
import respx

from cmlive.validate import compare, fetch_official, official_observed, summarize

# Excerto do exemplo oficial de /v2/arrivals/by_stop/:id (README da API da CM)
OFFICIAL = [
    {
        "estimated_arrival": "06:10:50",
        "estimated_arrival_unix": 1751778650,
        "headsign": "Carcavelos (Estação)",
        "line_id": "1604",
        "observed_arrival": "06:10:55",
        "observed_arrival_unix": 1751778655,
        "pattern_id": "1604_0_3",
        "route_id": "1604_0",
        "scheduled_arrival": "06:11:00",
        "scheduled_arrival_unix": 1751778660,
        "stop_sequence": 14,
        "trip_id": "1604_0_3_0600_0629_0_9_21NBI",
        "vehicle_id": "41|1217",
    },
    {"trip_id": "1604_0_3_0700_0729_0_9_21NBI", "observed_arrival_unix": None},
]


def test_only_observed_trips_are_kept():
    assert official_observed(OFFICIAL) == {"1604_0_3_0600_0629_0_9_21NBI": 1751778655.0}


def test_compare_and_summary():
    ours = {"1604_0_3_0600_0629_0_9_21NBI": 1751778665.0, "outra": 1.0}
    rows = compare(ours, official_observed(OFFICIAL), "121270")
    assert len(rows) == 1 and rows[0].error_s == 10
    s = summarize(rows)
    assert s["n"] == 1 and s["p50_abs_error_s"] == 10 and s["within_30s_pct"] == 100


def test_empty_summary():
    assert summarize([]) == {"n": 0}


@respx.mock
async def test_fetch_official():
    respx.get("https://api.test/v2/arrivals/by_stop/121270").respond(200, json=OFFICIAL)
    async with httpx.AsyncClient() as c:
        got = await fetch_official(c, "https://api.test/v2", "121270")
    assert list(got) == ["1604_0_3_0600_0629_0_9_21NBI"]
