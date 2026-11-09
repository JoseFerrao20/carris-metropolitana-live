import { classifyDelay, delayScale, formatDuration } from "./delay";

describe("classifyDelay", () => {
  it.each([
    [null, "unknown"],
    [undefined, "unknown"],
    [Number.NaN, "unknown"],
    [-61, "early"],
    [-60, "on_time"], // fronteira: 1 min adiantado ainda é pontual (igual ao backend)
    [0, "on_time"],
    [300, "on_time"], // fronteira: 5 min ainda é pontual
    [301, "late"],
    [600, "late"],
    [601, "very_late"],
  ])("%s → %s", (input, expected) => {
    expect(classifyDelay(input as number | null)).toBe(expected);
  });
});

describe("delayScale", () => {
  it("satura nos extremos", () => {
    expect(delayScale(-9999)).toBe("rgb(52, 120, 214)");
    expect(delayScale(9999)).toBe("rgb(214, 52, 44)");
  });
  it("é neutra no zero e interpola entre pontos", () => {
    expect(delayScale(0)).toBe("rgb(233, 233, 238)");
    expect(delayScale(150)).toBe("rgb(238, 205, 145)");
  });
});

describe("formatDuration", () => {
  it("usa segundos abaixo de 1 min e minutos acima, com vírgula decimal", () => {
    expect(formatDuration(12)).toBe("12,0 s");
    expect(formatDuration(95)).toBe("1,6 min");
    expect(formatDuration(-126)).toBe("-2,1 min");
  });
  it("mostra um traço quando não há valor", () => {
    expect(formatDuration(null)).toBe("–");
  });
});
