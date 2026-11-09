import type { DeltaMessage, LatencySamples, LatencyStage, Vehicle } from "../api/types";
import { RingBuffer } from "../lib/stats";

export type LngLat = readonly [number, number];

interface Entry {
  data: Vehicle;
  from: LngLat;
  to: LngLat;
  t0: number; // performance.now() do início da animação
}

export const ANIMATION_MS = 2000;

/** easeInOutQuad: começa e acaba devagar, para o veículo não "saltar". */
export function ease(k: number): number {
  const t = Math.min(1, Math.max(0, k));
  return t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
}

export function interpolate(from: LngLat, to: LngLat, k: number): LngLat {
  const e = ease(k);
  return [from[0] + (to[0] - from[0]) * e, from[1] + (to[1] - from[1]) * e];
}

const STAGES: LatencyStage[] = ["vehicle_to_browser", "collector_to_browser", "log_to_browser"];

export function emptySamples(): LatencySamples {
  return { vehicle_to_browser: [], collector_to_browser: [], log_to_browser: [] };
}

/**
 * Estado da frota no browser. Mutável e fora do React, de propósito: o mapa redesenha
 * a ~60 fps e o React só precisa de contadores uma vez por segundo.
 *
 * Regras:
 * - o snapshot inicial preenche o mapa mas NÃO conta como latência (mediria a idade do
 *   snapshot, até 5 min, e não a latência do stream);
 * - uma posição mais antiga do que a que temos é ignorada (o mapa só avança);
 * - uma mudança só de atraso (mesmo ts) atualiza a cor sem gerar amostra de latência.
 */
export class Fleet {
  private entries = new Map<string, Entry>();
  private pending: LatencySamples = emptySamples();
  private recent: Record<LatencyStage, RingBuffer> = {
    vehicle_to_browser: new RingBuffer(500),
    collector_to_browser: new RingBuffer(500),
    log_to_browser: new RingBuffer(500),
  };
  private updates: number[] = []; // instantes (s) de posições novas, para a taxa por minuto
  private lastChangeMs = -Infinity; // fim da última animação iniciada
  /** Incrementa a cada alteração visível (posição, cor ou remoção). */
  version = 0;

  get size(): number {
    return this.entries.size;
  }

  get(id: string): Vehicle | undefined {
    return this.entries.get(id)?.data;
  }

  applySnapshot(vehicles: readonly Vehicle[], nowMs: number): void {
    for (const v of vehicles) this.upsert(v, nowMs, null);
  }

  applyDelta(msg: Pick<DeltaMessage, "vehicles" | "removed">, nowMs: number, wallS: number): void {
    for (const v of msg.vehicles) this.upsert(v, nowMs, wallS);
    for (const id of msg.removed) if (this.entries.delete(id)) this.version++;
  }

  private upsert(v: Vehicle, nowMs: number, wallS: number | null): void {
    const cur = this.entries.get(v.vehicle_id);
    if (cur && v.ts < cur.data.ts) return;
    if (cur && v.ts === cur.data.ts && v.delay_s === cur.data.delay_s) return;
    const isNewPosition = !cur || v.ts > cur.data.ts;
    const from = cur ? this.positionOf(cur, nowMs) : ([v.lon, v.lat] as const);
    this.entries.set(v.vehicle_id, { data: v, from, to: [v.lon, v.lat], t0: nowMs });
    this.version++;
    this.lastChangeMs = Math.max(this.lastChangeMs, nowMs);
    if (wallS !== null && isNewPosition) {
      this.sample("vehicle_to_browser", wallS - v.ts);
      this.sample("collector_to_browser", wallS - v.collected_at);
      if (v.log_ts) this.sample("log_to_browser", wallS - v.log_ts);
      this.updates.push(wallS);
    }
  }

  private sample(stage: LatencyStage, value: number): void {
    if (!Number.isFinite(value) || value < 0) return;
    this.pending[stage].push(value);
    this.recent[stage].push(value);
  }

  private positionOf(e: Entry, nowMs: number): LngLat {
    return interpolate(e.from, e.to, (nowMs - e.t0) / ANIMATION_MS);
  }

  /** Há algum veículo a meio da animação? (se não, o mapa não precisa de ser redesenhado) */
  isAnimating(nowMs: number): boolean {
    return nowMs - this.lastChangeMs < ANIMATION_MS;
  }

  /** GeoJSON com a posição animada de cada veículo, opcionalmente filtrado por linha. */
  toGeoJSON(nowMs: number, lineFilter = ""): GeoJSON.FeatureCollection<GeoJSON.Point> {
    const features: GeoJSON.Feature<GeoJSON.Point>[] = [];
    for (const [id, e] of this.entries) {
      if (lineFilter && e.data.line_id !== lineFilter) continue;
      features.push({
        type: "Feature",
        id,
        geometry: { type: "Point", coordinates: [...this.positionOf(e, nowMs)] },
        properties: { id, line: e.data.line_id ?? "", delay: e.data.delay_s ?? -99999 },
      });
    }
    return { type: "FeatureCollection", features };
  }

  /** Amostras recentes (para o painel) — não são consumidas. */
  recentSamples(stage: LatencyStage): readonly number[] {
    return this.recent[stage].values();
  }

  /** Amostras ainda não enviadas ao servidor — são consumidas. */
  takePending(): LatencySamples {
    const out = this.pending;
    this.pending = emptySamples();
    return out;
  }

  hasPending(): boolean {
    return STAGES.some((s) => this.pending[s].length > 0);
  }

  updatesPerMinute(wallS: number): number {
    this.updates = this.updates.filter((t) => wallS - t < 60);
    return this.updates.length;
  }
}
