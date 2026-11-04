from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from cmlive.gtfs_time import (
    StopTime,
    format_gtfs_time,
    parse_gtfs_time,
    resolve_schedule,
    scheduled_epoch,
)

LX = ZoneInfo("Europe/Lisbon")


def ts(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=LX).timestamp()


@pytest.mark.parametrize("txt,sec", [("00:00:00", 0), ("06:20:00", 22800), ("25:10:30", 90630)])
def test_parse_and_format(txt, sec):
    assert parse_gtfs_time(txt) == sec
    assert format_gtfs_time(sec) == txt


def test_after_midnight_belongs_to_previous_service_day():
    # 25:10 do dia 10 = 01:10 do dia 11
    assert scheduled_epoch(date(2024, 6, 10), parse_gtfs_time("25:10:00"), LX) == ts(
        2024, 6, 11, 1, 10
    )


def test_dst_day_uses_noon_minus_12h():
    # 31/03/2024: os relógios avançam 01:00 → 02:00 em Lisboa.
    # Pela spec, "08:00:00" = (meio-dia − 12 h) + 8 h = 08:00 locais (WEST).
    # Contar a partir da meia-noite local daria 09:00, o que estaria errado.
    got = scheduled_epoch(date(2024, 3, 31), parse_gtfs_time("08:00:00"), LX)
    assert got == ts(2024, 3, 31, 8, 0)
    # Mudança de outubro (27/10/2024, 02:00 → 01:00)
    got = scheduled_epoch(date(2024, 10, 27), parse_gtfs_time("08:00:00"), LX)
    assert got == ts(2024, 10, 27, 8, 0)


STOP_TIMES = [
    StopTime(1, "A", parse_gtfs_time("23:50:00")),
    StopTime(2, "B", parse_gtfs_time("24:05:00")),
]


def test_resolve_picks_previous_service_day_after_midnight():
    m = resolve_schedule(STOP_TIMES, {date(2024, 6, 10)}, "B", ts(2024, 6, 11, 0, 7), LX)
    assert m.service_date == date(2024, 6, 10)
    assert m.stop_sequence == 2
    assert m.delay_s == 120


def test_resolve_respects_calendar():
    # A viagem não corre no dia 10 nem no dia 11: sem correspondência.
    assert resolve_schedule(STOP_TIMES, {date(2024, 6, 9)}, "B", ts(2024, 6, 11, 0, 7), LX) is None


def test_resolve_circular_route_picks_closest_occurrence():
    circ = [
        StopTime(1, "T", 8 * 3600),
        StopTime(2, "X", 8 * 3600 + 600),
        StopTime(3, "T", 9 * 3600),
    ]
    m = resolve_schedule(circ, {date(2024, 6, 10)}, "T", ts(2024, 6, 10, 9, 2), LX)
    assert m.stop_sequence == 3 and m.delay_s == 120


def test_resolve_early_is_negative_and_absurd_is_rejected():
    st = [StopTime(1, "A", 10 * 3600)]
    assert (
        resolve_schedule(st, {date(2024, 6, 10)}, "A", ts(2024, 6, 10, 9, 58), LX).delay_s == -120
    )
    assert resolve_schedule(st, {date(2024, 6, 10)}, "A", ts(2024, 6, 10, 18, 0), LX) is None
    assert resolve_schedule(st, {date(2024, 6, 10)}, "Z", ts(2024, 6, 10, 10, 0), LX) is None
