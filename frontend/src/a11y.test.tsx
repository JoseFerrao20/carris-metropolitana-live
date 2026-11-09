import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Heatmap } from "./components/Heatmap";
import { LivePanel } from "./components/LivePanel";
import { StopChart } from "./components/StopChart";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { LoginPage } from "./pages/LoginPage";
import { expectNoAxeViolations } from "./test/axe";
import { line, stop } from "./test/factories";
import { mockFetch, renderApp } from "./test/render";

const STATS = {
  positions_24h: 1,
  vehicles_10min: 1,
  arrivals_24h: 1,
  positions_size: "1 MB",
  arrivals_size: "1 MB",
  first_position: null,
  collector_to_db_p50_p95_s: [0.07, 0.14],
  vehicle_to_collector_p50_p95_s: [20, 30],
  live_vehicles: 1,
  sse_clients: 1,
};
const API = {
  "/api/stats": STATS,
  "/api/analytics/lines": [line({ line_id: "4512" }), line({ line_id: "1717" })],
  "/api/analytics/heatmap": [{ dow: 4, hour: 10, n: 100, avg_delay_s: 94, pct_on_time: 51.8 }],
  "/api/analytics/stops": [stop({ stop_sequence: 1 }), stop({ stop_id: "b", stop_sequence: 2 })],
};

describe("acessibilidade (axe-core, WCAG 2.1 AA)", () => {
  it("página de análise, sem sessão", async () => {
    mockFetch(API);
    const { container } = renderApp(<AnalyticsPage />, { route: "/analytics" });
    await screen.findByRole("button", { name: "1717" });
    await screen.findByRole("img", { name: /Atraso médio por paragem/ });
    await expectNoAxeViolations(container);
  });

  it("página de análise, com sessão e favoritas", async () => {
    mockFetch({ ...API, "/api/auth/me": { id: 1, email: "ana@exemplo.pt" }, "/api/me/favorites": ["1717"] });
    const { container } = renderApp(<AnalyticsPage />, { route: "/analytics" });
    await screen.findByRole("region", { name: "As minhas linhas" });
    await screen.findAllByRole("button", { name: /favoritas/ });
    await expectNoAxeViolations(container);
  });

  it("página de entrada, nos dois modos e com erro", async () => {
    mockFetch({ "/api/auth/login": new Response('{"detail":"Email ou password incorretos."}', { status: 401 }) });
    const { container } = renderApp(<LoginPage />, { route: "/entrar" });
    await expectNoAxeViolations(container);
    await userEvent.type(screen.getByLabelText("Email"), "a@b.pt");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
    await screen.findByRole("alert");
    await expectNoAxeViolations(container);
    await userEvent.click(screen.getByRole("button", { name: "Criar conta" }));
    await expectNoAxeViolations(container);
  });

  it("painel do mapa, com a opção de favoritas", async () => {
    mockFetch({});
    const { container } = renderApp(
      <LivePanel
        summary={{ vehicles: 10, updatesPerMinute: 5, vehicleToBrowserP50: 20, collectorToBrowserP50: 1 }}
        status="open"
        lineFilter=""
        onLineFilter={() => {}}
        favoritesCount={2}
        onlyFavorites={false}
        onOnlyFavorites={() => {}}
      />,
    );
    await screen.findByRole("link", { name: /Entrar/ });
    await expectNoAxeViolations(container, { isolated: true });
  });

  it("heatmap e gráfico por paragem", async () => {
    const { container } = renderApp(
      <>
        <Heatmap cells={[{ dow: 1, hour: 8, n: 5, avg_delay_s: 30, pct_on_time: 80 }]} />
        <StopChart lineId="1717" rows={[stop()]} />
      </>,
    );
    await expectNoAxeViolations(container, { isolated: true });
  });
});

describe("o próprio teste de acessibilidade", () => {
  it("deteta violações reais (controlo: campo sem etiqueta, imagem sem alt, botão vazio)", async () => {
    const div = document.createElement("div");
    div.innerHTML = '<input type="text"><img src="x.png"><button></button>';
    document.body.append(div);
    const err = await expectNoAxeViolations(div, { isolated: true }).then(() => null, (e: Error) => e);
    expect(err?.message).toMatch(/\blabel\b/);
    expect(err?.message).toMatch(/\bimage-alt\b/);
    expect(err?.message).toMatch(/\bbutton-name\b/);
    div.remove();
  });
});
