import { T0, vehicle } from "../test/factories";
import { ANIMATION_MS, ease, Fleet, interpolate } from "./fleet";

const WALL = T0 + 21;

describe("interpolação", () => {
  it("começa na origem, acaba no destino e é simétrica a meio", () => {
    expect(ease(0)).toBe(0);
    expect(ease(1)).toBe(1);
    expect(ease(0.5)).toBe(0.5);
    expect(ease(2)).toBe(1); // depois da animação fica parado no destino
    expect(interpolate([0, 0], [10, 20], 1)).toEqual([10, 20]);
  });
});

describe("Fleet", () => {
  it("o snapshot preenche o mapa mas não conta como latência", () => {
    const f = new Fleet();
    f.applySnapshot([vehicle(), vehicle({ vehicle_id: "b" })], 0);
    expect(f.size).toBe(2);
    expect(f.hasPending()).toBe(false);
    expect(f.updatesPerMinute(WALL)).toBe(0);
  });

  it("uma posição nova gera uma amostra por etapa", () => {
    const f = new Fleet();
    f.applyDelta({ vehicles: [vehicle()], removed: [] }, 0, WALL);
    const s = f.takePending();
    expect(s.vehicle_to_browser).toEqual([21]);
    expect(s.collector_to_browser).toEqual([1]);
    expect(s.log_to_browser[0]).toBeCloseTo(0.9);
    expect(f.hasPending()).toBe(false); // consumidas
    expect(f.recentSamples("vehicle_to_browser")).toEqual([21]); // mas continuam no painel
  });

  it("ignora posições mais antigas (o mapa só avança)", () => {
    const f = new Fleet();
    f.applyDelta({ vehicles: [vehicle({ ts: T0 + 30, lon: -9.0 })], removed: [] }, 0, WALL + 30);
    f.takePending();
    f.applyDelta({ vehicles: [vehicle({ ts: T0, lon: -9.5 })], removed: [] }, 10, WALL + 31);
    expect(f.get("[LA77N]1886")?.lon).toBe(-9.0);
    expect(f.hasPending()).toBe(false);
  });

  it("mudança só de atraso atualiza a cor sem amostra de latência", () => {
    const f = new Fleet();
    f.applyDelta({ vehicles: [vehicle()], removed: [] }, 0, WALL);
    f.takePending();
    f.applyDelta({ vehicles: [vehicle({ delay_s: 400 })], removed: [] }, 10, WALL + 1);
    expect(f.get("[LA77N]1886")?.delay_s).toBe(400);
    expect(f.hasPending()).toBe(false);
  });

  it("remove veículos e filtra por linha no GeoJSON", () => {
    const f = new Fleet();
    f.applySnapshot([vehicle(), vehicle({ vehicle_id: "b", line_id: "1604" })], 0);
    expect(f.toGeoJSON(0, "1604").features.map((x) => x.id)).toEqual(["b"]);
    f.applyDelta({ vehicles: [], removed: ["b"] }, 0, WALL);
    expect(f.toGeoJSON(0).features).toHaveLength(1);
  });

  it("anima da posição atual para a nova em ANIMATION_MS", () => {
    const f = new Fleet();
    f.applySnapshot([vehicle({ lon: -9.0 })], 0);
    f.applyDelta({ vehicles: [vehicle({ ts: T0 + 15, lon: -8.9 })], removed: [] }, 1000, WALL);
    const at = (t: number) => (f.toGeoJSON(t).features[0]!.geometry.coordinates[0] as number);
    expect(at(1000)).toBeCloseTo(-9.0);
    expect(at(1000 + ANIMATION_MS / 2)).toBeCloseTo(-8.95);
    expect(at(1000 + ANIMATION_MS)).toBeCloseTo(-8.9);
  });

  it("sem atraso medido, usa a sentinela que o mapa pinta de cinzento", () => {
    const f = new Fleet();
    f.applySnapshot([vehicle({ delay_s: null })], 0);
    expect(f.toGeoJSON(0).features[0]!.properties!.delay).toBe(-99999);
  });

  it("descarta amostras negativas (relógio do browser atrasado)", () => {
    const f = new Fleet();
    f.applyDelta({ vehicles: [vehicle()], removed: [] }, 0, T0 - 100);
    expect(f.hasPending()).toBe(false);
  });
});

describe("Fleet: deteção de alterações para o mapa", () => {
  it("versão sobe com posições, cores e remoções; animação termina ao fim de ANIMATION_MS", () => {
    const f = new Fleet();
    expect(f.isAnimating(0)).toBe(false);
    f.applySnapshot([vehicle()], 1000);
    const v1 = f.version;
    expect(f.isAnimating(1000 + ANIMATION_MS - 1)).toBe(true);
    expect(f.isAnimating(1000 + ANIMATION_MS)).toBe(false);
    f.applyDelta({ vehicles: [vehicle({ delay_s: 60 })], removed: [] }, 5000, WALL);
    expect(f.version).toBe(v1 + 1);
    f.applyDelta({ vehicles: [vehicle({ delay_s: 60 })], removed: ["nao-existe"] }, 6000, WALL);
    expect(f.version).toBe(v1 + 1); // nada mudou
  });
});
