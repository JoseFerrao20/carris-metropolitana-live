import type { LineStats, StopStats, Vehicle } from "../api/types";

export const T0 = 1_793_812_300;

export function vehicle(over: Partial<Vehicle> = {}): Vehicle {
  return {
    vehicle_id: "[LA77N]1886",
    ts: T0,
    lat: 38.7,
    lon: -9.1,
    bearing: null,
    speed: null,
    trip_id: "[7DQC0][LA77N]1252_0_3_1700_1729_0_1",
    line_id: "1252",
    route_id: "[LA77N]1252_0",
    stop_id: "171155",
    current_status: "IN_TRANSIT_TO",
    agency_id: "41",
    collected_at: T0 + 20,
    log_ts: T0 + 20.1,
    delay_s: null,
    ...over,
  };
}

export function line(over: Partial<LineStats> = {}): LineStats {
  return { line_id: "1717", n: 518, avg_delay_s: 456, pct_on_time: 30.3, pct_late: 60, pct_early: 9.7, ...over };
}

export function stop(over: Partial<StopStats> = {}): StopStats {
  return {
    pattern_id: "[LA77N]1717_0_2",
    direction_id: 1,
    headsign: "Colégio Militar (Metro)",
    stop_id: "360134",
    name: "Paragem",
    stop_sequence: 1,
    n: 10,
    avg_delay_s: 120,
    p50_delay_s: 100,
    p90_delay_s: 300,
    ...over,
  };
}
