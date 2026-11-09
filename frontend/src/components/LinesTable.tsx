import { useState } from "react";
import type { LineStats } from "../api/types";
import { formatDuration } from "../lib/delay";

const pct = (v: number) => `${v.toLocaleString("pt-PT")}%`;

interface Props {
  rows: LineStats[];
  selected: string | null;
  onSelect: (lineId: string) => void;
  top?: number;
}

export function LinesTable({ rows, selected, onSelect, top = 25 }: Props) {
  const [expanded, setExpanded] = useState(false);
  if (rows.length === 0) return <p className="muted">Ainda sem dados.</p>;
  const visible = expanded ? rows : rows.slice(0, top);
  return (
    <>
      <div className="table-scroll">
        <table className="lines">
          <thead>
            <tr>
              <th scope="col">Linha</th>
              <th scope="col">Chegadas</th>
              <th scope="col">Atraso médio</th>
              <th scope="col">% pontual</th>
              <th scope="col">% atrasado</th>
              <th scope="col">% adiantado</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.line_id} aria-selected={r.line_id === selected}>
                <th scope="row">
                  <button type="button" className="link" onClick={() => onSelect(r.line_id)}>
                    {r.line_id}
                  </button>
                </th>
                <td>{r.n.toLocaleString("pt-PT")}</td>
                <td>{formatDuration(r.avg_delay_s)}</td>
                <td>{pct(r.pct_on_time)}</td>
                <td>{pct(r.pct_late)}</td>
                <td>{pct(r.pct_early)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > top && (
        <button type="button" className="secondary" onClick={() => setExpanded((e) => !e)}>
          {expanded ? `Mostrar só as ${top} primeiras` : `Mostrar as ${rows.length} linhas`}
        </button>
      )}
    </>
  );
}
