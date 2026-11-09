import type { HeatCell, LatencySamples, LineStats, Stats, StopStats, User } from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly path: string,
    detail?: string,
  ) {
    super(detail ?? `HTTP ${status} em ${path}`);
    this.name = "ApiError";
  }
}

/** Mensagem do FastAPI: `detail` em texto, ou lista de erros de validação do pydantic. */
async function errorDetail(res: Response): Promise<string | undefined> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map((d: { msg?: string }) => d.msg ?? "").filter(Boolean).join(" ");
    }
  } catch {
    /* corpo não é JSON */
  }
  return undefined;
}

async function send<T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T | undefined> {
  const init: RequestInit = { method, credentials: "same-origin", headers: { accept: "application/json" } };
  if (body !== undefined) {
    init.headers = { ...init.headers, "content-type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (!res.ok) throw new ApiError(res.status, path, await errorDetail(res));
  return res.status === 204 ? undefined : ((await res.json()) as T);
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

  /** Utilizador da sessão atual, ou null se não houver sessão. */
  me: async (): Promise<User | null> => {
    try {
      return await getJson<User>("/api/auth/me");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return null;
      throw e;
    }
  },
  login: (email: string, password: string) => send<User>("POST", "/api/auth/login", { email, password }) as Promise<User>,
  register: (email: string, password: string) =>
    send<User>("POST", "/api/auth/register", { email, password }) as Promise<User>,
  logout: () => send<void>("POST", "/api/auth/logout").then(() => undefined),
  favorites: () => getJson<string[]>("/api/me/favorites"),
  addFavorite: (lineId: string) => send<void>("PUT", `/api/me/favorites/${encodeURIComponent(lineId)}`),
  removeFavorite: (lineId: string) => send<void>("DELETE", `/api/me/favorites/${encodeURIComponent(lineId)}`),

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
