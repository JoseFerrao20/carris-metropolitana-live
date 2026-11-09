import { useState } from "react";
import { LivePanel } from "../components/LivePanel";
import { MapView } from "../components/MapView";
import { useLiveFleet } from "../live/useLiveFleet";

export function LivePage() {
  const { fleet, status, summary } = useLiveFleet();
  const [lineFilter, setLineFilter] = useState("");
  return (
    <div className="live">
      <MapView fleet={fleet} lineFilter={lineFilter} />
      <LivePanel summary={summary} status={status} lineFilter={lineFilter} onLineFilter={setLineFilter} />
    </div>
  );
}
