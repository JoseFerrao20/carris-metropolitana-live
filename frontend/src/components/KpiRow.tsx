import type { Stats } from "../api/types";

const n = (v: number | undefined) => (v ?? 0).toLocaleString("pt-PT");
const pair = (p: [number, number] | null, unit: "s" | "ms") =>
  p === null
    ? "–"
    : unit === "s"
      ? `${p[0].toLocaleString("pt-PT", { maximumFractionDigits: 1 })} / ${p[1].toLocaleString("pt-PT", { maximumFractionDigits: 1 })} s`
      : `${Math.round(p[0] * 1000)} / ${Math.round(p[1] * 1000)} ms`;

export function KpiRow({ stats }: { stats: Stats }) {
  const items: Array<[string, string]> = [
    [n(stats.vehicles_10min), "veículos (10 min)"],
    [n(stats.positions_24h), "posições (24 h)"],
    [n(stats.arrivals_24h), "chegadas medidas (24 h)"],
    [stats.positions_size, "tamanho das posições"],
    [pair(stats.vehicle_to_collector_p50_p95_s, "s"), "veículo→coletor p50/p95"],
    [pair(stats.collector_to_db_p50_p95_s, "ms"), "coletor→BD p50/p95"],
  ];
  return (
    <dl className="card kpis">
      {items.map(([value, label]) => (
        <div key={label}>
          <dd>{value}</dd>
          <dt>{label}</dt>
        </div>
      ))}
    </dl>
  );
}
