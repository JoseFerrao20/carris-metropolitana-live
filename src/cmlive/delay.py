"""Deteção de chegadas às paragens e reordenação de eventos (lógica pura, sem I/O).

Fluxo por veículo::

    posições (podem vir repetidas/fora de ordem)
        → ReorderBuffer (watermark = max_ts − janela)
        → VehicleTracker (máquina de estados por viagem)
        → Arrival(trip_id, stop_id, observed_ts, método, incerteza)
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable
from dataclasses import dataclass, field

from .models import VehiclePosition

EARTH_R = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------- reordenação


@dataclass
class ReorderBuffer:
    """Reordena eventos por veículo dentro de uma janela de tolerância.

    Um evento é libertado quando o seu ``ts`` fica abaixo do watermark do veículo
    (``max_ts − window_s``) ou quando já esperou ``window_s`` em tempo de relógio.
    Eventos com ``ts`` ≤ ao último libertado chegaram tarde demais: são descartados e contados.
    """

    window_s: float = 20.0
    _heaps: dict[str, list[tuple[int, int, VehiclePosition]]] = field(default_factory=dict)
    _max_ts: dict[str, int] = field(default_factory=dict)
    _released: dict[str, int] = field(default_factory=dict)
    _seq: int = 0
    late: int = 0
    duplicates: int = 0

    def push(self, pos: VehiclePosition) -> bool:
        vid = pos.vehicle_id
        last = self._released.get(vid)
        if last is not None and pos.ts <= last:
            if pos.ts == last:
                self.duplicates += 1
            else:
                self.late += 1
            return False
        heap = self._heaps.setdefault(vid, [])
        if any(item[0] == pos.ts for item in heap):
            self.duplicates += 1
            return False
        self._seq += 1
        heapq.heappush(heap, (pos.ts, self._seq, pos))
        self._max_ts[vid] = max(self._max_ts.get(vid, pos.ts), pos.ts)
        return True

    def pop_ready(self, now: float) -> list[VehiclePosition]:
        out: list[VehiclePosition] = []
        for vid, heap in self._heaps.items():
            watermark = self._max_ts[vid] - self.window_s
            while heap and (
                heap[0][0] <= watermark or heap[0][2].collected_at <= now - self.window_s
            ):
                ts, _, pos = heapq.heappop(heap)
                self._released[vid] = ts
                out.append(pos)
        out.sort(key=lambda p: (p.ts, p.vehicle_id))
        return out

    def drain(self) -> list[VehiclePosition]:
        return self.pop_ready(now=math.inf)

    def pending(self) -> int:
        return sum(len(h) for h in self._heaps.values())


# --------------------------------------------------------------------------- deteção


@dataclass(frozen=True, slots=True)
class Arrival:
    vehicle_id: str
    trip_id: str
    stop_id: str
    observed_ts: float
    method: str  # stopped | passed | departed | geofence
    uncertainty_s: float
    line_id: str | None
    route_id: str | None


StopCoords = Callable[[str], tuple[float, float] | None]


@dataclass
class VehicleTracker:
    """Máquina de estados de um veículo. Recebe posições **por ordem**.

    Regras (``stop_id`` segue a semântica GTFS-RT: paragem atual ou a próxima):

    1. ``STOPPED_AT X`` pela primeira vez nesta viagem ⇒ chegada a X, no ponto médio
       entre a observação anterior e esta (método ``stopped``).
    2. ``stop_id`` muda de X para Y sem termos registado X ⇒ o veículo passou por X
       sem parar (ou não o vimos parado): chegada no ponto médio (``passed``).
    3. Se a primeira observação da viagem já é ``STOPPED_AT X`` (ex.: no terminal),
       não sabemos quando chegou: registamos a partida de X (``departed``).
    4. *Geofence* opcional: a ≤ N m da paragem conta como chegada (``geofence``).

    A ``uncertainty_s`` é metade do intervalo entre as duas observações que
    enquadram o evento. As análises podem filtrar por ela.
    """

    vehicle_id: str
    max_gap_s: float = 300.0
    geofence_m: float = 40.0
    stop_coords: StopCoords | None = None
    trip_id: str | None = None
    stop_id: str | None = None
    status: str | None = None
    ts: float | None = None
    line_id: str | None = None
    route_id: str | None = None
    emitted: set[str] = field(default_factory=set)
    unknown_arrival: str | None = None
    skipped_gap: int = 0

    def _arrival(self, stop_id: str, t0: float, t1: float, method: str) -> Arrival | None:
        gap = t1 - t0
        if gap > self.max_gap_s:
            self.skipped_gap += 1
            self.emitted.add(stop_id)
            return None
        self.emitted.add(stop_id)
        return Arrival(
            self.vehicle_id,
            self.trip_id or "",
            stop_id,
            (t0 + t1) / 2,
            method,
            gap / 2,
            self.line_id,
            self.route_id,
        )

    def update(self, pos: VehiclePosition) -> list[Arrival]:
        out: list[Arrival] = []
        if pos.trip_id != self.trip_id:
            # Nova viagem (ou fim de serviço): reinicia o estado.
            self.trip_id, self.emitted, self.unknown_arrival = pos.trip_id, set(), None
            self.stop_id, self.status, self.ts = pos.stop_id, pos.current_status, pos.ts
            self.line_id, self.route_id = pos.line_id, pos.route_id
            if pos.current_status == "STOPPED_AT" and pos.stop_id:
                self.unknown_arrival = pos.stop_id
            elif pos.trip_id and pos.stop_id:
                self._maybe_geofence(pos, pos.ts, out)
            return out

        if not self.trip_id or self.ts is None:
            self.stop_id, self.status, self.ts = pos.stop_id, pos.current_status, pos.ts
            return out

        prev_ts, prev_stop = self.ts, self.stop_id

        # Regra 2/3: saiu da paragem anterior.
        if prev_stop and pos.stop_id != prev_stop and prev_stop not in self.emitted:
            method = "departed" if self.unknown_arrival == prev_stop else "passed"
            a = self._arrival(prev_stop, prev_ts, pos.ts, method)
            if a:
                out.append(a)

        # Regra 1: parado na paragem atual.
        if (
            pos.current_status == "STOPPED_AT"
            and pos.stop_id
            and pos.stop_id not in self.emitted
            and self.unknown_arrival != pos.stop_id
        ):
            a = self._arrival(pos.stop_id, prev_ts, pos.ts, "stopped")
            if a:
                out.append(a)
        elif pos.stop_id:
            self._maybe_geofence(pos, prev_ts, out)

        self.stop_id, self.status, self.ts = pos.stop_id, pos.current_status, pos.ts
        self.line_id, self.route_id = pos.line_id or self.line_id, pos.route_id or self.route_id
        return out

    def _maybe_geofence(self, pos: VehiclePosition, prev_ts: float, out: list[Arrival]) -> None:
        if not self.stop_coords or not pos.stop_id or pos.stop_id in self.emitted:
            return
        coords = self.stop_coords(pos.stop_id)
        if coords and haversine_m(pos.lat, pos.lon, *coords) <= self.geofence_m:
            a = self._arrival(pos.stop_id, prev_ts, pos.ts, "geofence")
            if a:
                out.append(a)


@dataclass
class ArrivalDetector:
    """Junta o ReorderBuffer com um VehicleTracker por veículo."""

    window_s: float = 20.0
    geofence_m: float = 40.0
    stop_coords: StopCoords | None = None
    trackers: dict[str, VehicleTracker] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.buffer = ReorderBuffer(self.window_s)

    def push(self, pos: VehiclePosition) -> bool:
        return self.buffer.push(pos)

    def _feed(self, ready: list[VehiclePosition]) -> list[Arrival]:
        out: list[Arrival] = []
        for pos in ready:
            tr = self.trackers.get(pos.vehicle_id)
            if tr is None:
                tr = VehicleTracker(
                    pos.vehicle_id, geofence_m=self.geofence_m, stop_coords=self.stop_coords
                )
                self.trackers[pos.vehicle_id] = tr
            out.extend(tr.update(pos))
        return out

    def poll(self, now: float) -> list[Arrival]:
        return self._feed(self.buffer.pop_ready(now))

    def flush(self) -> list[Arrival]:
        return self._feed(self.buffer.drain())
