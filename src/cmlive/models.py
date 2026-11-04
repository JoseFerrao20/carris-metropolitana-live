"""Modelo de evento de posição e normalização da resposta de ``/v2/vehicles``.

Ver ``docs/API.md`` para as particularidades da fonte que justificam cada regra.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any

import orjson

# Caixa larga à volta da AML: rejeita (0,0) e coordenadas trocadas.
LAT_RANGE = (37.5, 39.5)
LON_RANGE = (-10.0, -8.0)

VALID_STATUS = {"INCOMING_AT", "STOPPED_AT", "IN_TRANSIT_TO"}

_PLAN_PREFIX = re.compile(r"^\[[^\]]*\]")


def normalize_timestamp(raw: Any) -> int | None:
    """Devolve epoch em **segundos** (UTC).

    A documentação oficial diz "milissegundos", o exemplo mostra segundos e o código
    atual divide por 1000. Aceitamos os dois: valores acima de 1e12 são ms.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    if value > 1e12:
        value /= 1000.0
    return int(value)


def normalize_trip_id(raw: Any) -> str | None:
    """Remove o prefixo ``[plano]`` que versões antigas da API acrescentavam."""
    if not raw:
        return None
    trip = _PLAN_PREFIX.sub("", str(raw)).strip()
    return trip or None


def _float(raw: Any) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _str(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


@dataclass(frozen=True, slots=True)
class VehiclePosition:
    vehicle_id: str
    ts: int  # instante da posição reportado pelo veículo (epoch s, UTC)
    lat: float
    lon: float
    bearing: float | None
    speed: float | None
    trip_id: str | None
    line_id: str | None
    route_id: str | None
    stop_id: str | None
    current_status: str | None
    agency_id: str | None
    collected_at: float  # instante em que o coletor recebeu a resposta (epoch s)

    @property
    def key(self) -> tuple[str, int]:
        return (self.vehicle_id, self.ts)

    def to_json(self) -> bytes:
        return orjson.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: bytes | str | dict) -> VehiclePosition:
        d = data if isinstance(data, dict) else orjson.loads(data)
        return cls(**{f: d.get(f) for f in cls.__slots__})


class RejectReason:
    NO_ID = "no_id"
    BAD_TS = "bad_timestamp"
    BAD_COORDS = "bad_coordinates"
    STALE = "stale"
    FUTURE = "future"


def parse_vehicle(
    raw: dict[str, Any], *, collected_at: float, stale_after_s: int = 300
) -> tuple[VehiclePosition | None, str | None]:
    """Converte um elemento de ``/v2/vehicles``.

    Devolve ``(posição, None)`` ou ``(None, motivo)``.
    """
    vid = _str(raw.get("id"))
    if not vid:
        return None, RejectReason.NO_ID

    ts = normalize_timestamp(raw.get("timestamp"))
    if ts is None:
        return None, RejectReason.BAD_TS
    if ts > collected_at + 120:  # relógio do veículo adiantado
        return None, RejectReason.FUTURE
    if ts < collected_at - stale_after_s:
        return None, RejectReason.STALE

    lat, lon = _float(raw.get("lat")), _float(raw.get("lon"))
    if (
        lat is None
        or lon is None
        or not (LAT_RANGE[0] <= lat <= LAT_RANGE[1])
        or not (LON_RANGE[0] <= lon <= LON_RANGE[1])
    ):
        return None, RejectReason.BAD_COORDS

    status = _str(raw.get("current_status"))
    if status not in VALID_STATUS:
        status = None

    return (
        VehiclePosition(
            vehicle_id=vid,
            ts=ts,
            lat=lat,
            lon=lon,
            bearing=_float(raw.get("bearing")),
            speed=_float(raw.get("speed")),
            trip_id=normalize_trip_id(raw.get("trip_id")),
            line_id=_str(raw.get("line_id")),
            route_id=_str(raw.get("route_id")),
            stop_id=_str(raw.get("stop_id")),
            current_status=status,
            agency_id=_str(raw.get("agency_id")),
            collected_at=collected_at,
        ),
        None,
    )
