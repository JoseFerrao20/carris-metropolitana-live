import { useEffect, useState, type DependencyList } from "react";

export type AsyncState<T> =
  | { status: "loading"; data?: undefined; error?: undefined }
  | { status: "success"; data: T; error?: undefined }
  | { status: "error"; data?: undefined; error: Error };

/**
 * Corre `fn` quando as dependências mudam e cancela o pedido anterior (AbortController),
 * para uma resposta antiga nunca se sobrepor a uma mais recente.
 */
export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: DependencyList): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    setState({ status: "loading" });
    fn(ctrl.signal).then(
      (data) => !ctrl.signal.aborted && setState({ status: "success", data }),
      (err: unknown) => {
        if (ctrl.signal.aborted) return;
        setState({ status: "error", error: err instanceof Error ? err : new Error(String(err)) });
      },
    );
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- as dependências são as do chamador
  }, deps);

  return state;
}
