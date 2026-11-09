import { act, renderHook } from "@testing-library/react";
import { T0, vehicle } from "../test/factories";
import { useLiveFleet } from "./useLiveFleet";

/** EventSource mínimo controlado pelo teste. */
class FakeEventSource extends EventTarget {
  closed = false;
  constructor(public url: string) {
    super();
  }
  emit(type: string, data?: unknown) {
    const ev = data === undefined ? new Event(type) : new MessageEvent(type, { data: JSON.stringify(data) });
    this.dispatchEvent(ev);
  }
  close() {
    this.closed = true;
  }
}

function setup() {
  let es: FakeEventSource | undefined;
  const fetchSpy = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", fetchSpy);
  const hook = renderHook(() =>
    useLiveFleet({
      eventSource: (url) => (es = new FakeEventSource(url)) as unknown as EventSource,
      summaryEveryMs: 1000,
      reportEveryMs: 10_000,
      now: () => 0,
      wallClock: () => T0 + 21,
    }),
  );
  return { hook, es: () => es!, fetchSpy };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useLiveFleet", () => {
  it("liga-se a /api/stream e reflete o estado da ligação", () => {
    const { hook, es } = setup();
    expect(es().url).toBe("/api/stream");
    expect(hook.result.current.status).toBe("connecting");
    act(() => es().emit("snapshot", { type: "snapshot", sent_at: T0, vehicles: [vehicle()] }));
    expect(hook.result.current.status).toBe("open");
    act(() => es().emit("error"));
    expect(hook.result.current.status).toBe("reconnecting");
  });

  it("atualiza o resumo uma vez por segundo, sem contar o snapshot como latência", () => {
    const { hook, es } = setup();
    act(() => {
      es().emit("snapshot", { type: "snapshot", sent_at: T0, vehicles: [vehicle({ vehicle_id: "a" })] });
      es().emit("delta", { type: "delta", sent_at: T0, vehicles: [vehicle({ vehicle_id: "b" })], removed: [] });
    });
    act(() => vi.advanceTimersByTime(1000));
    expect(hook.result.current.summary).toEqual({
      vehicles: 2,
      updatesPerMinute: 1, // só o delta
      vehicleToBrowserP50: 21,
      collectorToBrowserP50: 1,
    });
  });

  it("envia as amostras de latência ao servidor e fecha a ligação ao desmontar", () => {
    const { hook, es, fetchSpy } = setup();
    act(() => es().emit("delta", { type: "delta", sent_at: T0, vehicles: [vehicle()], removed: [] }));
    act(() => vi.advanceTimersByTime(10_000));
    expect(fetchSpy).toHaveBeenCalledWith("/api/latency", expect.objectContaining({ method: "POST" }));
    const body = JSON.parse(fetchSpy.mock.calls[0]![1].body as string);
    expect(body.vehicle_to_browser).toEqual([21]);

    act(() => vi.advanceTimersByTime(10_000));
    expect(fetchSpy).toHaveBeenCalledTimes(1); // sem amostras novas, não envia

    hook.unmount();
    expect(es().closed).toBe(true);
  });
});
