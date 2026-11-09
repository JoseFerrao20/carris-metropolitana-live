/** Quantil com interpolação linear (igual a percentile_cont do Postgres). */
export function quantile(values: readonly number[], q: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = (sorted.length - 1) * Math.min(1, Math.max(0, q));
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  const a = sorted[lo]!;
  const b = sorted[hi]!;
  return a + (b - a) * (pos - lo);
}

export const median = (values: readonly number[]) => quantile(values, 0.5);

/** Buffer circular de tamanho fixo (amostras recentes para o painel). */
export class RingBuffer {
  private items: number[] = [];
  constructor(private readonly capacity: number) {}

  push(v: number): void {
    this.items.push(v);
    if (this.items.length > this.capacity) this.items.shift();
  }

  values(): readonly number[] {
    return this.items;
  }

  get size(): number {
    return this.items.length;
  }
}
