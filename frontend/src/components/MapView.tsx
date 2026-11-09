import maplibregl, { type GeoJSONSource, type Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import type { Vehicle } from "../api/types";
import { DELAY_COLOR, EARLY_S, ON_TIME_MAX_S, VERY_LATE_S, formatDuration } from "../lib/delay";
import type { Fleet } from "../live/fleet";

interface Props {
  fleet: Fleet;
  lineFilter: string;
}

const UNKNOWN = -99999; // sentinela para "sem atraso medido" na propriedade `delay`

/**
 * Cada setData faz o MapLibre reprocessar todo o GeoJSON num worker. A 60 fps, com ~1 000
 * veículos, isso ocupava o CPU (medido: 25% da main thread num browser sem GPU) e atrasava
 * a navegação. Os veículos movem-se a cada ~15 s, por isso 20 fps chegam para a animação.
 */
export const MAX_FPS = 20;

/** Decide se este frame deve enviar dados novos ao mapa. */
export function shouldRedraw(
  nowMs: number,
  last: { atMs: number; version: number; filter: string },
  fleet: Pick<Fleet, "version" | "isAnimating">,
  filter: string,
): boolean {
  if (nowMs - last.atMs < 1000 / MAX_FPS) return false;
  return fleet.isAnimating(nowMs) || fleet.version !== last.version || filter !== last.filter;
}

/** Popup em DOM (não HTML em string), para não haver injeção a partir dos dados. */
export function vehiclePopup(v: Vehicle, wallS: number): HTMLElement {
  const root = document.createElement("div");
  const rows: Array<[string, string]> = [
    ["Veículo", v.vehicle_id],
    ["Paragem", `${v.stop_id ?? "?"} (${v.current_status ?? "?"})`],
    ["Atraso", v.delay_s === null ? "sem dados" : formatDuration(v.delay_s)],
    ["Posição de há", `${Math.max(0, Math.round(wallS - v.ts))} s`],
  ];
  const title = document.createElement("strong");
  title.textContent = `Linha ${v.line_id ?? "?"}`;
  root.append(title);
  for (const [k, val] of rows) {
    const line = document.createElement("div");
    line.textContent = `${k}: ${val}`;
    root.append(line);
  }
  return root;
}

export function MapView({ fleet, lineFilter }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const filterRef = useRef(lineFilter);
  filterRef.current = lineFilter;

  useEffect(() => {
    if (!container.current) return;
    const map: MapLibreMap = new maplibregl.Map({
      container: container.current,
      center: [-9.1, 38.7],
      zoom: 10,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tileSize: 256,
            maxzoom: 19,
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            attribution: "© OpenStreetMap · dados: Carris Metropolitana (CC BY 4.0)",
          },
        },
        layers: [
          { id: "osm", type: "raster", source: "osm", paint: { "raster-saturation": -0.6, "raster-opacity": 0.9 } },
        ],
      },
    });

    let frame = 0;
    map.on("load", () => {
      map.addSource("vehicles", { type: "geojson", data: fleet.toGeoJSON(performance.now()) });
      map.addLayer({
        id: "vehicles",
        type: "circle",
        source: "vehicles",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 2.5, 14, 7],
          "circle-stroke-width": 1,
          "circle-stroke-color": "#ffffff",
          // Camada WebGL: 1 000+ pontos animados sem tocar no DOM.
          "circle-color": [
            "case",
            ["==", ["get", "delay"], UNKNOWN], DELAY_COLOR.unknown,
            ["<", ["get", "delay"], EARLY_S], DELAY_COLOR.early,
            ["<=", ["get", "delay"], ON_TIME_MAX_S], DELAY_COLOR.on_time,
            ["<=", ["get", "delay"], VERY_LATE_S], DELAY_COLOR.late,
            DELAY_COLOR.very_late,
          ],
        },
      });

      map.on("click", "vehicles", (e) => {
        const id = e.features?.[0]?.properties?.id as string | undefined;
        const v = id ? fleet.get(id) : undefined;
        if (!v) return;
        new maplibregl.Popup().setLngLat(e.lngLat).setDOMContent(vehiclePopup(v, Date.now() / 1000)).addTo(map);
      });
      map.on("mouseenter", "vehicles", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "vehicles", () => (map.getCanvas().style.cursor = ""));

      const last = { atMs: -Infinity, version: -1, filter: "" };
      const draw = () => {
        const now = performance.now();
        if (shouldRedraw(now, last, fleet, filterRef.current)) {
          const src = map.getSource("vehicles") as GeoJSONSource | undefined;
          src?.setData(fleet.toGeoJSON(now, filterRef.current));
          Object.assign(last, { atMs: now, version: fleet.version, filter: filterRef.current });
        }
        frame = requestAnimationFrame(draw);
      };
      frame = requestAnimationFrame(draw);
    });

    return () => {
      cancelAnimationFrame(frame);
      map.remove();
    };
  }, [fleet]);

  return <div ref={container} className="map" role="region" aria-label="Mapa com os veículos em tempo real" />;
}
