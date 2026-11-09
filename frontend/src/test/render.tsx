import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../auth/AuthContext";
import { ROUTER_FUTURE } from "../routerFuture";

export type Routes = Record<string, unknown | ((init?: RequestInit) => unknown)>;

/**
 * Simula a API: `routes` mapeia o caminho (sem query) para o corpo JSON, uma Response,
 * ou uma função (para respostas que dependem do método). /api/auth/me devolve 401 por omissão.
 */
export function mockFetch(routes: Routes) {
  const all: Routes = { "/api/auth/me": new Response('{"detail":"Sessão inválida"}', { status: 401 }), ...routes };
  const spy = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    let body = all[url.pathname];
    if (typeof body === "function") body = (body as (i?: RequestInit) => unknown)(init);
    if (body instanceof Response) return body.clone();
    if (body === undefined) return new Response("", { status: 404 });
    if (body === null) return new Response(null, { status: 204 });
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

export function renderApp(ui: ReactElement, { route = "/" }: { route?: string } = {}) {
  return render(
    <MemoryRouter future={ROUTER_FUTURE} initialEntries={[route]}>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>,
  );
}
