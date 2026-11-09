// Classificação e cores dos atrasos. "Pontual" = entre 1 min adiantado e 5 min atrasado,
// a mesma definição usada no backend (delay_hourly) e no README.

export type DelayClass = "unknown" | "early" | "on_time" | "late" | "very_late";

export const EARLY_S = -60;
export const ON_TIME_MAX_S = 300;
export const VERY_LATE_S = 600;

export function classifyDelay(delayS: number | null | undefined): DelayClass {
  if (delayS === null || delayS === undefined || Number.isNaN(delayS)) return "unknown";
  if (delayS < EARLY_S) return "early";
  if (delayS <= ON_TIME_MAX_S) return "on_time";
  if (delayS <= VERY_LATE_S) return "late";
  return "very_late";
}

export const DELAY_LABEL: Record<DelayClass, string> = {
  early: "adiantado",
  on_time: "≤ 5 min",
  late: "5–10 min",
  very_late: "> 10 min",
  unknown: "sem dados",
};

/** Cores por classe (as mesmas em claro e escuro; foram escolhidas para contrastar com os dois mapas). */
export const DELAY_COLOR: Record<DelayClass, string> = {
  early: "#3478d6",
  on_time: "#1a9e5c",
  late: "#e8a317",
  very_late: "#d6342c",
  unknown: "#8e8e93",
};

type Rgb = readonly [number, number, number];
const SCALE: ReadonlyArray<readonly [number, Rgb]> = [
  [-120, [52, 120, 214]],
  [0, [233, 233, 238]],
  [300, [242, 177, 52]],
  [600, [214, 52, 44]],
];

/** Escala divergente contínua para o heatmap: azul (adiantado) → neutro → âmbar → vermelho. */
export function delayScale(delayS: number): string {
  const first = SCALE[0]!;
  const last = SCALE[SCALE.length - 1]!;
  if (delayS <= first[0]) return rgb(first[1]);
  for (let i = 1; i < SCALE.length; i++) {
    const [b, cb] = SCALE[i]!;
    if (delayS <= b) {
      const [a, ca] = SCALE[i - 1]!;
      const k = (delayS - a) / (b - a);
      return rgb([0, 1, 2].map((n) => Math.round(ca[n]! + (cb[n]! - ca[n]!) * k)) as unknown as Rgb);
    }
  }
  return rgb(last[1]);
}

function rgb([r, g, b]: Rgb): string {
  return `rgb(${r}, ${g}, ${b})`;
}

/** 95 → "1,6 min"; 12 → "12 s"; null → "–". Formato português (vírgula decimal). */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "–";
  const fmt = (v: number) => v.toLocaleString("pt-PT", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return Math.abs(seconds) < 60 ? `${fmt(seconds)} s` : `${fmt(seconds / 60)} min`;
}
