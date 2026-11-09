// Espelho do JSON devolvido pelo backend (src/cmlive/web/app.py).

export type VehicleStatus = "INCOMING_AT" | "STOPPED_AT" | "IN_TRANSIT_TO";

/** Uma posição de veículo, tal como sai do log de eventos (ver cmlive.models.VehiclePosition). */
export interface Vehicle {
  vehicle_id: string;
  ts: number; // instante reportado pelo veículo (epoch s)
  lat: number;
  lon: number;
  bearing: number | null;
  speed: number | null;
  trip_id: string | null;
  line_id: string | null;
  route_id: string | null;
  stop_id: string | null;
  current_status: VehicleStatus | null;
  agency_id: string | null;
  collected_at: number; // instante em que o coletor recebeu a resposta (epoch s)
  log_ts?: number | null; // instante em que entrou no Redpanda (epoch s)
  delay_s: number | null; // último atraso medido para este veículo
}

export interface SnapshotMessage {
  type: "snapshot";
  sent_at: number;
  vehicles: Vehicle[];
}

export interface DeltaMessage {
  type: "delta";
  sent_at: number;
  vehicles: Vehicle[];
  removed: string[];
}

export interface LineStats {
  line_id: string;
  n: number;
  avg_delay_s: number;
  pct_on_time: number;
  pct_late: number;
  pct_early: number;
}

export interface HeatCell {
  dow: number; // 1 = segunda … 7 = domingo (ISO)
  hour: number;
  n: number;
  avg_delay_s: number;
  pct_on_time: number;
}

export interface StopStats {
  pattern_id: string | null;
  direction_id: number | null;
  headsign: string | null;
  stop_id: string;
  name: string | null;
  stop_sequence: number;
  n: number;
  avg_delay_s: number;
  p50_delay_s: number;
  p90_delay_s: number;
}

export interface Stats {
  positions_24h: number;
  vehicles_10min: number;
  arrivals_24h: number;
  positions_size: string;
  arrivals_size: string;
  first_position: string | null;
  collector_to_db_p50_p95_s: [number, number] | null;
  vehicle_to_collector_p50_p95_s: [number, number] | null;
  live_vehicles: number;
  sse_clients: number;
}

export type LatencyStage = "vehicle_to_browser" | "collector_to_browser" | "log_to_browser";
export type LatencySamples = Record<LatencyStage, number[]>;
