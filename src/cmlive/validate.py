"""Valida as chegadas detetadas contra o ``observed_arrival`` oficial da Carris Metropolitana.

``GET /v2/arrivals/by_stop/:id`` devolve, por viagem, ``scheduled_arrival_unix`` e
``observed_arrival_unix`` (ver docs/API.md). Comparamos o nosso ``observed_at`` com o
oficial para a mesma (viagem, paragem) e resumimos o erro.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

import httpx

from .models import normalize_trip_id


@dataclass(frozen=True, slots=True)
class Comparison:
    trip_id: str
    stop_id: str
    ours: float
    official: float

    @property
    def error_s(self) -> float:
        return self.ours - self.official


def official_observed(payload: list[dict[str, Any]]) -> dict[str, float]:
    """trip_id → observed_arrival_unix (só as que já têm observação)."""
    out = {}
    for item in payload:
        trip = normalize_trip_id(item.get("trip_id"))
        obs = item.get("observed_arrival_unix")
        if trip and isinstance(obs, int | float) and obs > 0:
            out[trip] = float(obs)
    return out


def compare(ours: dict[str, float], official: dict[str, float], stop_id: str) -> list[Comparison]:
    return [
        Comparison(trip, stop_id, ours[trip], official[trip])
        for trip in sorted(ours.keys() & official.keys())
    ]


def summarize(rows: list[Comparison]) -> dict[str, float | int]:
    if not rows:
        return {"n": 0}
    errs = sorted(abs(r.error_s) for r in rows)
    return {
        "n": len(rows),
        "mean_error_s": round(statistics.fmean(r.error_s for r in rows), 1),
        "p50_abs_error_s": errs[len(errs) // 2],
        "p90_abs_error_s": errs[min(len(errs) - 1, int(len(errs) * 0.9))],
        "within_30s_pct": round(100 * sum(e <= 30 for e in errs) / len(errs), 1),
    }


async def fetch_official(
    client: httpx.AsyncClient, base_url: str, stop_id: str
) -> dict[str, float]:
    r = await client.get(f"{base_url.rstrip('/')}/arrivals/by_stop/{stop_id}")
    r.raise_for_status()
    return official_observed(r.json())
