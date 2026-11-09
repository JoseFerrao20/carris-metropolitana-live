import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Heatmap } from "../components/Heatmap";
import { KpiRow } from "../components/KpiRow";
import { LinesTable } from "../components/LinesTable";
import { StopChart } from "../components/StopChart";
import { useAsync, type AsyncState } from "../lib/useAsync";

function Loadable<T>({ state, children }: { state: AsyncState<T>; children: (data: T) => React.ReactNode }) {
  if (state.status === "loading") return <p className="muted" aria-busy="true">A carregar…</p>;
  if (state.status === "error") return <p role="alert">Não foi possível carregar: {state.error.message}</p>;
  return <>{children(state.data)}</>;
}

export function AnalyticsPage() {
  const stats = useAsync((s) => api.stats(s), []);
  const lines = useAsync((s) => api.lines(7, s), []);
  const [heatLine, setHeatLine] = useState("");
  const heat = useAsync((s) => api.heatmap(heatLine || undefined, 28, s), [heatLine]);
  const [picked, setPicked] = useState<string | null>(null);

  // Por omissão, mostra a linha com mais atraso.
  const selected = picked ?? (lines.status === "success" ? (lines.data[0]?.line_id ?? null) : null);
  const stops = useAsync((s) => (selected ? api.stops(selected, 7, s) : Promise.resolve([])), [selected]);
  const lineIds = lines.status === "success" ? lines.data.map((l) => l.line_id).sort() : [];

  return (
    <main className="analytics">
      <header>
        <h1>Análise de atrasos</h1>
        <p className="muted">
          Atraso = chegada observada − hora planeada no GTFS. Pontual: entre 1 min adiantado e 5 min atrasado. O
          heatmap e o ranking só usam horas planeadas com recolha contínua de H−30 min a H+90 min.{" "}
          <Link to="/">← mapa ao vivo</Link>
        </p>
      </header>

      <Loadable state={stats}>{(s) => <KpiRow stats={s} />}</Loadable>

      <section className="card" aria-labelledby="heat-title">
        <h2 id="heat-title">
          Dia da semana × hora{" "}
          <select aria-label="Linha do heatmap" value={heatLine} onChange={(e) => setHeatLine(e.target.value)}>
            <option value="">todas as linhas</option>
            {lineIds.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        </h2>
        <Loadable state={heat}>{(cells) => <Heatmap cells={cells} />}</Loadable>
      </section>

      <section className="card" aria-labelledby="stops-title">
        <h2 id="stops-title">{selected ? `Atraso médio por paragem: linha ${selected}` : "Atraso médio por paragem"}</h2>
        {selected ? (
          <Loadable state={stops}>{(rows) => <StopChart key={selected} lineId={selected} rows={rows} />}</Loadable>
        ) : (
          <p className="muted">Escolha uma linha na tabela.</p>
        )}
      </section>

      <section className="card" aria-labelledby="lines-title">
        <h2 id="lines-title">Linhas com mais atraso (últimos 7 dias, mín. 100 chegadas)</h2>
        <Loadable state={lines}>{(rows) => <LinesTable rows={rows} selected={selected} onSelect={setPicked} />}</Loadable>
      </section>
    </main>
  );
}
