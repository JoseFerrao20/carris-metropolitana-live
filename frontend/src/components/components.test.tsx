import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { line, stop, vehicle } from "../test/factories";
import { mockFetch, renderApp } from "../test/render";
import { Heatmap } from "./Heatmap";
import { LinesTable } from "./LinesTable";
import { LivePanel } from "./LivePanel";
import { groupByPattern, StopChart } from "./StopChart";

vi.mock("maplibre-gl", () => ({ default: {} })); // MapView importa-o; o jsdom não tem WebGL
const { vehiclePopup } = await import("./MapView");

describe("Heatmap", () => {
  it("pinta só as células com dados e descreve-as para leitores de ecrã", () => {
    render(<Heatmap cells={[{ dow: 4, hour: 10, n: 38736, avg_delay_s: 94, pct_on_time: 51.8 }]} />);
    const cell = screen.getByLabelText(/Qui 10h/);
    expect(cell).toHaveAttribute("title", expect.stringContaining("1,6 min"));
    expect(cell).toHaveAttribute("title", expect.stringContaining("38 736 chegadas"));
    expect(cell.getAttribute("style")).toContain("background");
  });

  it("explica quando ainda não há horas com cobertura completa", () => {
    render(<Heatmap cells={[]} />);
    expect(screen.getByText(/sem horas com cobertura completa/)).toBeInTheDocument();
  });
});

describe("StopChart", () => {
  const rows = [
    stop({ pattern_id: "p1", direction_id: 0, headsign: "Barcarena", stop_id: "a", stop_sequence: 2, n: 5 }),
    stop({ pattern_id: "p2", direction_id: 1, headsign: "Colégio Militar", stop_id: "x", stop_sequence: 1, n: 50 }),
    stop({ pattern_id: "p1", direction_id: 0, headsign: "Barcarena", stop_id: "b", stop_sequence: 1, n: 5 }),
  ];

  it("agrupa por percurso, ordena as paragens e põe primeiro o mais observado", () => {
    const groups = groupByPattern(rows);
    expect(groups.map((g) => g.id)).toEqual(["p2", "p1"]);
    expect(groups[1]!.stops.map((s) => s.stop_id)).toEqual(["b", "a"]);
  });

  it("mostra um percurso de cada vez e deixa trocar de sentido", async () => {
    render(<StopChart lineId="1717" rows={rows} />);
    expect(screen.getByRole("img", { name: /Colégio Militar/ })).toBeInTheDocument();
    expect(screen.getAllByRole("img")[0]!.querySelectorAll("rect")).toHaveLength(1);

    await userEvent.selectOptions(screen.getByLabelText(/Percurso/), "p1");
    expect(screen.getByRole("img", { name: /Barcarena/ }).querySelectorAll("rect")).toHaveLength(2);
  });
});

describe("LinesTable", () => {
  const rows = Array.from({ length: 30 }, (_, i) => line({ line_id: String(1000 + i) }));

  it("mostra as 25 primeiras e expande para todas", async () => {
    render(<LinesTable rows={rows} selected={null} onSelect={() => {}} />);
    expect(screen.getAllByRole("row")).toHaveLength(26); // + cabeçalho
    await userEvent.click(screen.getByRole("button", { name: "Mostrar as 30 linhas" }));
    expect(screen.getAllByRole("row")).toHaveLength(31);
  });

  it("seleciona uma linha com o teclado e marca-a", async () => {
    const onSelect = vi.fn();
    const { rerender } = render(<LinesTable rows={rows.slice(0, 3)} selected={null} onSelect={onSelect} />);
    screen.getByRole("button", { name: "1001" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith("1001");
    rerender(<LinesTable rows={rows.slice(0, 3)} selected="1001" onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: "1001" }).closest("tr")).toHaveAttribute("aria-selected", "true");
  });
});

describe("LivePanel", () => {
  it("mostra o resumo, a legenda e o estado da ligação", async () => {
    const onFilter = vi.fn();
    mockFetch({});
    renderApp(
      <LivePanel
          summary={{ vehicles: 1296, updatesPerMinute: 3500, vehicleToBrowserP50: 20.8, collectorToBrowserP50: 0.77 }}
          status="reconnecting"
          lineFilter=""
          onLineFilter={onFilter}
        />,
    );
    expect(screen.getByTestId("vehicles")).toHaveTextContent("1296"); // pt-PT não agrupa 4 dígitos
    expect(screen.getByText("20,8 s")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Legenda das cores")).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByRole("status")).toHaveTextContent("a religar");
    await userEvent.type(screen.getByPlaceholderText(/Filtrar por linha/), "1");
    expect(onFilter).toHaveBeenCalledWith("1");
  });
});

describe("vehiclePopup", () => {
  it("usa texto e nunca interpreta HTML vindo dos dados", () => {
    const el = vehiclePopup(vehicle({ line_id: "<img src=x onerror=alert(1)>", delay_s: 95 }), vehicle().ts + 30);
    expect(el.querySelector("img")).toBeNull();
    expect(el.textContent).toContain("Linha <img src=x onerror=alert(1)>");
    expect(el.textContent).toContain("Atraso: 1,6 min");
    expect(el.textContent).toContain("Posição de há: 30 s");
  });
});
