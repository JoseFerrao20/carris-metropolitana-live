import { Link } from "react-router-dom";
import { DELAY_COLOR, DELAY_LABEL, formatDuration, type DelayClass } from "../lib/delay";
import type { ConnectionStatus, FleetSummary } from "../live/useLiveFleet";

interface Props {
  summary: FleetSummary;
  status: ConnectionStatus;
  lineFilter: string;
  onLineFilter: (v: string) => void;
}

const STATUS_TEXT: Record<ConnectionStatus, string> = {
  connecting: "a ligar…",
  open: "ligado · SSE",
  reconnecting: "ligação perdida, a religar…",
};

const LEGEND: DelayClass[] = ["early", "on_time", "late", "very_late", "unknown"];

export function LivePanel({ summary, status, lineFilter, onLineFilter }: Props) {
  return (
    <aside className="panel" aria-label="Resumo ao vivo">
      <h1>Carris Metropolitana · ao vivo</h1>
      <dl className="stats">
        <div>
          <dt>veículos no mapa</dt>
          <dd data-testid="vehicles">{summary.vehicles.toLocaleString("pt-PT")}</dd>
        </div>
        <div>
          <dt>atualizações/min</dt>
          <dd>{summary.updatesPerMinute.toLocaleString("pt-PT")}</dd>
        </div>
        <div>
          <dt>idade p50 (veículo→browser)</dt>
          <dd>{formatDuration(summary.vehicleToBrowserP50)}</dd>
        </div>
        <div>
          <dt>p50 coletor→browser</dt>
          <dd>{formatDuration(summary.collectorToBrowserP50)}</dd>
        </div>
      </dl>
      <ul className="legend" aria-label="Legenda das cores">
        {LEGEND.map((c) => (
          <li key={c}>
            <i className="dot" style={{ background: DELAY_COLOR[c] }} aria-hidden="true" />
            {DELAY_LABEL[c]}
          </li>
        ))}
      </ul>
      <label className="filter">
        <span className="visually-hidden">Filtrar por linha</span>
        <input
          value={lineFilter}
          onChange={(e) => onLineFilter(e.target.value.trim())}
          placeholder="Filtrar por linha (ex.: 1604)"
          inputMode="numeric"
        />
      </label>
      <p className="muted" role="status">
        {STATUS_TEXT[status]}
      </p>
      <Link to="/analytics">Análise de atrasos →</Link>
    </aside>
  );
}
