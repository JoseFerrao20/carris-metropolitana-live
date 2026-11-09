import { useMemo, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { LivePanel } from "../components/LivePanel";
import { MapView } from "../components/MapView";
import { buildFilter } from "../live/fleet";
import { useLiveFleet } from "../live/useLiveFleet";

export function LivePage() {
  const { fleet, status, summary } = useLiveFleet();
  const { favorites } = useAuth();
  const [lineFilter, setLineFilter] = useState("");
  const [onlyFavorites, setOnlyFavorites] = useState(false);
  const useFavorites = onlyFavorites && favorites.size > 0;
  const filter = useMemo(() => buildFilter(lineFilter, useFavorites, favorites), [lineFilter, useFavorites, favorites]);
  return (
    <div className="live">
      <MapView fleet={fleet} filter={filter} />
      <LivePanel
        summary={summary}
        status={status}
        lineFilter={lineFilter}
        onLineFilter={setLineFilter}
        favoritesCount={favorites.size}
        onlyFavorites={useFavorites}
        onOnlyFavorites={setOnlyFavorites}
      />
    </div>
  );
}
