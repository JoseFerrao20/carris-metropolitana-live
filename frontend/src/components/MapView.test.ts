export {};
vi.mock("maplibre-gl", () => ({ default: {} }));
const { MAX_FPS, shouldRedraw } = await import("./MapView");

const fleet = (animating: boolean, version = 1) => ({ version, isAnimating: () => animating });
const FRAME = 1000 / MAX_FPS;

describe("shouldRedraw", () => {
  const last = { atMs: 0, version: 1, filter: "" };
  it("respeita o limite de fps", () => {
    expect(shouldRedraw(FRAME - 1, last, fleet(true), "")).toBe(false);
    expect(shouldRedraw(FRAME, last, fleet(true), "")).toBe(true);
  });
  it("não redesenha se nada mudou e nada está a animar", () => {
    expect(shouldRedraw(10_000, last, fleet(false), "")).toBe(false);
  });
  it("redesenha quando chegam dados novos ou muda o filtro", () => {
    expect(shouldRedraw(10_000, last, fleet(false, 2), "")).toBe(true);
    expect(shouldRedraw(10_000, last, fleet(false), "1717")).toBe(true);
  });
});
