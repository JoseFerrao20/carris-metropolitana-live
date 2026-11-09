import { median, quantile, RingBuffer } from "./stats";

describe("quantile", () => {
  it("interpola como o percentile_cont do Postgres", () => {
    expect(quantile([1, 2, 3, 4], 0.5)).toBe(2.5);
    expect(quantile([10, 20, 30, 40, 50], 0.9)).toBe(46);
    expect(median([3, 1, 2])).toBe(2);
  });
  it("devolve null sem amostras e não altera a entrada", () => {
    const xs = [3, 1, 2];
    expect(quantile([], 0.5)).toBeNull();
    quantile(xs, 0.5);
    expect(xs).toEqual([3, 1, 2]);
  });
});

describe("RingBuffer", () => {
  it("guarda só as últimas N amostras", () => {
    const b = new RingBuffer(3);
    [1, 2, 3, 4, 5].forEach((v) => b.push(v));
    expect(b.values()).toEqual([3, 4, 5]);
    expect(b.size).toBe(3);
  });
});
