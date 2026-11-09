import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { DeltaMessage, SnapshotMessage } from "../api/types";
import { median } from "../lib/stats";
import { Fleet } from "./fleet";

export type ConnectionStatus = "connecting" | "open" | "reconnecting";

export interface FleetSummary {
  vehicles: number;
  updatesPerMinute: number;
  vehicleToBrowserP50: number | null;
  collectorToBrowserP50: number | null;
}

export interface UseLiveFleetOptions {
  url?: string;
  /** Injeção para testes. */
  eventSource?: (url: string) => EventSource;
  summaryEveryMs?: number;
  reportEveryMs?: number;
  now?: () => number; // relógio de animação (ms)
  wallClock?: () => number; // relógio de parede (s)
}

const EMPTY: FleetSummary = {
  vehicles: 0,
  updatesPerMinute: 0,
  vehicleToBrowserP50: null,
  collectorToBrowserP50: null,
};

/**
 * Liga-se a /api/stream (SSE) e mantém a frota atualizada. O EventSource religa
 * sozinho (o servidor envia `retry: 3000`); aqui só refletimos o estado da ligação.
 */
export function useLiveFleet(opts: UseLiveFleetOptions = {}) {
  const {
    url = "/api/stream",
    eventSource = (u: string) => new EventSource(u),
    summaryEveryMs = 1000,
    reportEveryMs = 10_000,
    now = () => performance.now(),
    wallClock = () => Date.now() / 1000,
  } = opts;

  const fleetRef = useRef<Fleet>(new Fleet());
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [summary, setSummary] = useState<FleetSummary>(EMPTY);

  // As funções de relógio/injeção são estáveis por design; não queremos religar a cada render.
  const deps = useRef({ eventSource, now, wallClock });
  deps.current = { eventSource, now, wallClock };

  useEffect(() => {
    const fleet = fleetRef.current;
    const es = deps.current.eventSource(url);

    const onSnapshot = (e: MessageEvent<string>) => {
      const msg = JSON.parse(e.data) as SnapshotMessage;
      fleet.applySnapshot(msg.vehicles, deps.current.now());
      setStatus("open");
    };
    const onDelta = (e: MessageEvent<string>) => {
      const msg = JSON.parse(e.data) as DeltaMessage;
      fleet.applyDelta(msg, deps.current.now(), deps.current.wallClock());
    };
    const onError = () => setStatus("reconnecting");

    es.addEventListener("snapshot", onSnapshot as EventListener);
    es.addEventListener("delta", onDelta as EventListener);
    es.addEventListener("error", onError);

    const summaryTimer = setInterval(() => {
      const t = deps.current.wallClock();
      setSummary({
        vehicles: fleet.size,
        updatesPerMinute: fleet.updatesPerMinute(t),
        vehicleToBrowserP50: median(fleet.recentSamples("vehicle_to_browser")),
        collectorToBrowserP50: median(fleet.recentSamples("collector_to_browser")),
      });
    }, summaryEveryMs);

    const reportTimer = setInterval(() => {
      if (fleet.hasPending()) void api.reportLatency(fleet.takePending());
    }, reportEveryMs);

    return () => {
      es.removeEventListener("snapshot", onSnapshot as EventListener);
      es.removeEventListener("delta", onDelta as EventListener);
      es.removeEventListener("error", onError);
      es.close();
      clearInterval(summaryTimer);
      clearInterval(reportTimer);
    };
  }, [url, summaryEveryMs, reportEveryMs]);

  return { fleet: fleetRef.current, status, summary };
}
