import type { Page } from "@playwright/test";

export const T0 = Math.floor(Date.now() / 1000);

const vehicle = (id: string, line: string, lon: number, delay: number | null) => ({
  vehicle_id: id,
  ts: T0 - 20,
  lat: 38.72,
  lon,
  bearing: null,
  speed: null,
  trip_id: `[7DQC0][LA77N]${line}_0_1`,
  line_id: line,
  route_id: null,
  stop_id: "171155",
  current_status: "IN_TRANSIT_TO",
  agency_id: "41",
  collected_at: T0 - 1,
  log_ts: T0 - 1,
  delay_s: delay,
});

// PNG 1×1 transparente, para não depender dos tiles do OpenStreetMap.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

export interface MockOptions {
  /** Utilizador com sessão (o servidor simulado guarda as favoritas em memória). */
  user?: { id: number; email: string } | null;
  favorites?: string[];
}

export async function mockApi(page: Page, opts: MockOptions = {}) {
  let user = opts.user ?? null;
  const favorites = new Set(opts.favorites ?? []);
  await page.route("**/api/auth/me", (r) =>
    user ? r.fulfill({ json: user }) : r.fulfill({ status: 401, json: { detail: "Sessão inválida ou expirada." } }),
  );
  await page.route("**/api/auth/login", async (r) => {
    const body = r.request().postDataJSON() as { email: string; password: string };
    if (body.password !== "password-correta") {
      return r.fulfill({ status: 401, json: { detail: "Email ou password incorretos." } });
    }
    user = { id: 1, email: body.email };
    return r.fulfill({ json: user });
  });
  await page.route("**/api/auth/logout", (r) => {
    user = null;
    return r.fulfill({ status: 204 });
  });
  await page.route("**/api/me/favorites", (r) => r.fulfill({ json: [...favorites].sort() }));
  await page.route("**/api/me/favorites/*", (r) => {
    const id = decodeURIComponent(r.request().url().split("/").pop()!);
    if (r.request().method() === "PUT") favorites.add(id);
    else favorites.delete(id);
    return r.fulfill({ status: 204 });
  });
  await page.route("https://tile.openstreetmap.org/**", (r) => r.fulfill({ body: PNG, contentType: "image/png" }));
  await page.route("**/api/stream", (r) =>
    r.fulfill({
      contentType: "text/event-stream",
      body:
        "retry: 60000\nevent: snapshot\ndata: " +
        JSON.stringify({
          type: "snapshot",
          sent_at: T0,
          vehicles: [vehicle("a", "1717", -9.2, 1200), vehicle("b", "1604", -9.1, 30), vehicle("c", "1717", -9.0, null)],
        }) +
        "\n\n",
    }),
  );
  await page.route("**/api/latency", (r) => r.fulfill({ json: { ok: true } }));
  await page.route("**/api/stats", (r) =>
    r.fulfill({
      json: {
        positions_24h: 867034,
        vehicles_10min: 910,
        arrivals_24h: 167573,
        positions_size: "295 MB",
        arrivals_size: "40 MB",
        first_position: null,
        collector_to_db_p50_p95_s: [0.072, 0.149],
        vehicle_to_collector_p50_p95_s: [20.3, 30.6],
        live_vehicles: 900,
        sse_clients: 1,
      },
    }),
  );
  await page.route("**/api/analytics/lines**", (r) =>
    r.fulfill({
      json: [
        { line_id: "4512", n: 500, avg_delay_s: 582, pct_on_time: 35.2, pct_late: 60, pct_early: 4.8 },
        { line_id: "1717", n: 518, avg_delay_s: 456, pct_on_time: 30.3, pct_late: 60, pct_early: 9.7 },
      ],
    }),
  );
  await page.route("**/api/analytics/heatmap**", (r) =>
    r.fulfill({ json: [{ dow: 4, hour: 10, n: 38736, avg_delay_s: 94, pct_on_time: 51.8 }] }),
  );
  await page.route("**/api/analytics/stops**", (r) => {
    const line = new URL(r.request().url()).searchParams.get("line_id");
    return r.fulfill({
      json: [1, 2, 3].map((seq) => ({
        pattern_id: `${line}_0_1`,
        direction_id: 0,
        headsign: `Destino ${line}`,
        stop_id: `s${seq}`,
        name: `Paragem ${seq}`,
        stop_sequence: seq,
        n: 10,
        avg_delay_s: 60 * seq,
        p50_delay_s: 60 * seq,
        p90_delay_s: 90 * seq,
      })),
    });
  });
}

