"""Tempo GTFS: horas > 24:00, dia de serviço e mudança de hora."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo


def parse_gtfs_time(value: str) -> int:
    """``"25:10:30"`` → 90630 segundos desde o início do dia de serviço."""
    h, m, s = value.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def format_gtfs_time(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def service_day_origin(service_date: date, tz: ZoneInfo) -> datetime:
    """Origem dos tempos GTFS: "meio-dia menos 12 h" (spec GTFS, stop_times.txt).

    Nos dias de mudança de hora isto difere da meia-noite local em ±1 h, e é
    precisamente o que a especificação exige: assim, as horas *depois* da mudança
    coincidem com o relógio de parede.

    Atenção: somar ``timedelta`` a um ``datetime`` com fuso faz aritmética de relógio
    de parede, por isso a conta tem de ser feita em UTC.
    """
    noon = datetime(service_date.year, service_date.month, service_date.day, 12, tzinfo=tz)
    return noon.astimezone(UTC) - timedelta(hours=12)


def scheduled_epoch(service_date: date, gtfs_seconds: int, tz: ZoneInfo) -> float:
    return (service_day_origin(service_date, tz) + timedelta(seconds=gtfs_seconds)).timestamp()


@dataclass(frozen=True, slots=True)
class StopTime:
    stop_sequence: int
    stop_id: str
    arrival_s: int


@dataclass(frozen=True, slots=True)
class ScheduleMatch:
    stop_sequence: int
    service_date: date
    scheduled_ts: float
    delay_s: float


def resolve_schedule(
    stop_times: Iterable[StopTime],
    active_dates: set[date],
    stop_id: str,
    observed_ts: float,
    tz: ZoneInfo,
    max_abs_delay_s: float = 3 * 3600,
) -> ScheduleMatch | None:
    """Escolhe o par (dia de serviço, ocorrência da paragem) mais próximo do instante observado.

    - Uma viagem que começa às 23:50 tem paragens a "24:10" no dia de serviço anterior,
      por isso testamos o dia local e o anterior.
    - Em linhas circulares a mesma paragem aparece duas vezes na viagem: fica a mais próxima.
    """
    local_day = datetime.fromtimestamp(observed_ts, tz).date()
    candidates_days = [d for d in (local_day, local_day - timedelta(days=1)) if d in active_dates]
    best: ScheduleMatch | None = None
    for st in stop_times:
        if st.stop_id != stop_id:
            continue
        for d in candidates_days:
            sched = scheduled_epoch(d, st.arrival_s, tz)
            delay = observed_ts - sched
            if abs(delay) > max_abs_delay_s:
                continue
            if best is None or abs(delay) < abs(best.delay_s):
                best = ScheduleMatch(st.stop_sequence, d, sched, delay)
    return best
