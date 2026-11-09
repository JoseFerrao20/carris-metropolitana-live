import type { HeatCell, LatencySamples, LineStats, Stats, StopStats } from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly path: string,
  ) {
    super(`HTTP ${status} em ${path}`);
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string, params: Record<string, string | number | undefined> = {}, signal?: AbortSignal): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const url = qs.size ? `${path}?${qs.toString()}` : path;
  const init: RequestInit = { headers: { accept: "application/json" } };
  if (signal) init.signal = signal;
  const res = await fetch(url, init);
  if (!res.ok) throw new ApiError(res.status, path);
  return (await res.json()) as T;
}

export const api = {
  stats: (signal?: AbortSignal) => getJson<Stats>("/api/stats", {}, signal),
  lines: (days = 7, signal?: AbortSignal) => getJson<LineStats[]>("/api/analytics/lines", { days }, signal),
  heatmap: (lineId?: string, days = 28, signal?: AbortSignal) =>
    getJson<HeatCell[]>("/api/analytics/heatmap", { line_id: lineId, days }, signal),
  stops: (lineId: string, days = 7, signal?: AbortSignal) =>
    getJson<StopStats[]>("/api/analytics/stops", { line_id: lineId, days }, signal),

  /** Envia amostras de latência medidas no browser. Falhas são ignoradas (é telemetria). */
  reportLatency: async (samples: LatencySamples): Promise<void> => {
    try {
      await fetch("/api/latency", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(samples),
        keepalive: true,
      });
    } catch {
      /* telemetria: não interessa ao utilizador */
    }
  },
};
