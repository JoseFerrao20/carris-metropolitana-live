import { useMemo, useState } from "react";
import type { StopStats } from "../api/types";
import { formatDuration } from "../lib/delay";

export interface Pattern {
  id: string;
  label: string;
  total: number;
  stops: StopStats[];
}

/**
 * Agrupa por percurso (pattern), do mais observado para o menos. Misturar sentidos
 * intercala paragens de viagens diferentes e dá um gráfico enganador.
 */
export function groupByPattern(rows: readonly StopStats[]): Pattern[] {
  const map = new Map<string, Pattern>();
  for (const r of rows) {
    const id = r.pattern_id ?? "?";
    let p = map.get(id);
    if (!p) {
      p = { id, label: `sentido ${r.direction_id ?? "?"} → ${r.headsign ?? id}`, total: 0, stops: [] };
      map.set(id, p);
    }
    p.total += r.n;
    p.stops.push(r);
  }
  const out = [...map.values()];
  for (const p of out) p.stops.sort((a, b) => a.stop_sequence - b.stop_sequence);
  return out.sort((a, b) => b.total - a.total);
}

const H = 220;
const PAD = 34;
const BAR = 16;

export function StopChart({ lineId, rows }: { lineId: string; rows: StopStats[] }) {
  const patterns = useMemo(() => groupByPattern(rows), [rows]);
  const [selected, setSelected] = useState<string | null>(null);
  const current = patterns.find((p) => p.id === selected) ?? patterns[0];

  if (!current) return <p className="muted">Sem chegadas medidas para a linha {lineId}.</p>;

  const values = current.stops.map((s) => s.avg_delay_s);
  const max = Math.max(60, ...values);
  const min = Math.min(0, ...values);
  const y = (v: number) => PAD + ((H - 2 * PAD) * (max - v)) / (max - min);
  const W = Math.max(600, current.stops.length * BAR + 2 * PAD);

  return (
    <div>
      <label className="inline-select">
        Percurso{" "}
        <select value={current.id} onChange={(e) => setSelected(e.target.value)}>
          {patterns.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
      </label>
      <div className="chart-scroll">
        <svg width={W} height={H} role="img" aria-label={`Atraso médio por paragem, linha ${lineId}, ${current.label}`}>
          <line className="axis" x1={PAD} x2={W - PAD} y1={y(0)} y2={y(0)} />
          <text x={2} y={y(max) + 4}>
            {formatDuration(max)}
          </text>
          <text x={2} y={y(0) + 4}>
            0
          </text>
          {current.stops.map((s, i) => {
            const top = Math.min(y(0), y(s.avg_delay_s));
            const h = Math.max(1, Math.abs(y(s.avg_delay_s) - y(0)));
            return (
              <rect key={`${s.stop_id}-${s.stop_sequence}`} className="bar" x={PAD + i * BAR + 1} y={top} width={BAR - 2} height={h}>
                <title>
                  #{s.stop_sequence} {s.name ?? s.stop_id}: média {formatDuration(s.avg_delay_s)}, p90 {formatDuration(s.p90_delay_s)} ({s.n} chegadas)
                </title>
              </rect>
            );
          })}
        </svg>
      </div>
      <p className="muted small">Paragens por ordem no percurso; passe o rato para ver os detalhes.</p>
    </div>
  );
}
