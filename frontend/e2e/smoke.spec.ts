import { expect, test, type Page } from "@playwright/test";

const T0 = Math.floor(Date.now() / 1000);

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

async function mockApi(page: Page) {
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

test("mapa ao vivo: recebe o snapshot por SSE e desenha os veículos", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByTestId("vehicles")).toHaveText("3");
  await expect(page.getByRole("status")).toContainText(/ligado|a religar/);
  await expect(page.locator(".map canvas")).toBeVisible();
  await page.getByPlaceholder(/Filtrar por linha/).fill("1717");
  await page.getByRole("link", { name: /Análise de atrasos/ }).click();
  await expect(page).toHaveURL(/\/analytics$/);
  expect(errors).toEqual([]);
});

test("análise: KPIs, heatmap, ranking e gráfico por paragem", async ({ page }) => {
  await mockApi(page);
  await page.goto("/analytics");
  await expect(page.getByText("72 / 149 ms")).toBeVisible();
  await expect(page.getByLabel(/Qui 10h/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Atraso médio por paragem: linha 4512" })).toBeVisible();
  await page.getByRole("button", { name: "1717" }).click();
  await expect(page.getByRole("img", { name: /linha 1717/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /linha 1717/ }).locator("rect")).toHaveCount(3);
});
