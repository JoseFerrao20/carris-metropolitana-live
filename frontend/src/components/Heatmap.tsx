import type { HeatCell } from "../api/types";
import { delayScale, formatDuration } from "../lib/delay";

export const DOW = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"] as const;
const HOURS = Array.from({ length: 24 }, (_, h) => h);

export function cellLabel(c: HeatCell): string {
  return `${DOW[c.dow - 1]} ${c.hour}h: atraso médio ${formatDuration(c.avg_delay_s)} · ${c.n.toLocaleString("pt-PT")} chegadas · ${c.pct_on_time.toLocaleString("pt-PT")}% pontual`;
}

/** Dia da semana × hora. Só recebe horas com cobertura completa (filtradas no backend). */
export function Heatmap({ cells }: { cells: HeatCell[] }) {
  if (cells.length === 0) {
    return <p className="muted">Ainda sem horas com cobertura completa de recolha.</p>;
  }
  const byKey = new Map(cells.map((c) => [`${c.dow}-${c.hour}`, c]));
  return (
    <div className="heat-scroll">
      <table className="heat" aria-label="Atraso médio por dia da semana e hora planeada">
        <thead>
          <tr>
            <th scope="col">
              <span className="visually-hidden">Dia</span>
            </th>
            {HOURS.map((h) => (
              <th key={h} scope="col">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {DOW.map((day, i) => (
            <tr key={day}>
              <th scope="row">{day}</th>
              {HOURS.map((h) => {
                const c = byKey.get(`${i + 1}-${h}`);
                return c ? (
                  <td key={h} style={{ background: delayScale(c.avg_delay_s) }} title={cellLabel(c)} aria-label={cellLabel(c)} />
                ) : (
                  <td key={h} />
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="scale" aria-hidden="true">
        adiantado <i /> &gt; 10 min
      </div>
    </div>
  );
}
