import { ROUTER_FUTURE } from "../routerFuture";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { Stats } from "../api/types";
import { line, stop } from "../test/factories";
import { AnalyticsPage } from "./AnalyticsPage";

const STATS: Stats = {
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
};

function mockApi(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    "/api/stats": STATS,
    "/api/analytics/lines": [line({ line_id: "4512" }), line({ line_id: "1717" })],
    "/api/analytics/heatmap": [{ dow: 4, hour: 10, n: 100, avg_delay_s: 94, pct_on_time: 51.8 }],
    "/api/analytics/stops": [stop()],
    ...overrides,
  };
  const spy = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    const body = routes[url.pathname];
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

const renderPage = () =>
  render(
    <MemoryRouter future={ROUTER_FUTURE}>
      <AnalyticsPage />
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllGlobals());

describe("AnalyticsPage", () => {
  it("carrega KPIs, heatmap, ranking e o gráfico da linha com mais atraso", async () => {
    const spy = mockApi();
    renderPage();
    expect(await screen.findByText("72 / 149 ms")).toBeInTheDocument();
    expect(await screen.findByLabelText(/Qui 10h/)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Atraso médio por paragem: linha 4512" })).toBeInTheDocument();
    await waitFor(() =>
      expect(spy.mock.calls.some(([u]) => String(u) === "/api/analytics/stops?line_id=4512&days=7")).toBe(true),
    );
  });

  it("ao escolher outra linha na tabela, pede as paragens dessa linha", async () => {
    const spy = mockApi();
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "1717" }));
    expect(await screen.findByRole("heading", { name: "Atraso médio por paragem: linha 1717" })).toBeInTheDocument();
    await waitFor(() =>
      expect(spy.mock.calls.some(([u]) => String(u) === "/api/analytics/stops?line_id=1717&days=7")).toBe(true),
    );
  });

  it("filtra o heatmap por linha", async () => {
    const spy = mockApi();
    renderPage();
    await screen.findByRole("button", { name: "1717" });
    await userEvent.selectOptions(screen.getByLabelText("Linha do heatmap"), "1717");
    await waitFor(() =>
      expect(spy.mock.calls.some(([u]) => String(u) === "/api/analytics/heatmap?line_id=1717&days=28")).toBe(true),
    );
  });

  it("mostra um erro legível se a API falhar, sem partir o resto da página", async () => {
    mockApi({ "/api/stats": new Response("x", { status: 503 }) });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 503 em /api/stats");
    expect(await screen.findByRole("button", { name: "4512" })).toBeInTheDocument();
  });
});
