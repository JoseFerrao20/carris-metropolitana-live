import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { AccountBar } from "../components/AccountBar";
import { AnalyticsPage } from "../pages/AnalyticsPage";
import { LoginPage } from "../pages/LoginPage";
import { line, stop } from "../test/factories";
import { mockFetch, renderApp } from "../test/render";

const USER = { id: 1, email: "ana@exemplo.pt" };

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderLogin() {
  return renderApp(
    <Routes>
      <Route path="/entrar" element={<LoginPage />} />
      <Route path="*" element={<Where />} />
    </Routes>,
    { route: "/entrar" },
  );
}

describe("LoginPage", () => {
  it("entra e segue para a análise", async () => {
    const spy = mockFetch({ "/api/auth/login": USER, "/api/me/favorites": [] });
    renderLogin();
    await userEvent.type(screen.getByLabelText("Email"), USER.email);
    await userEvent.type(screen.getByLabelText("Password"), "uma-password-boa");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByTestId("where")).toHaveTextContent("/analytics");
    const [, init] = spy.mock.calls.find(([u]) => String(u) === "/api/auth/login")!;
    expect(JSON.parse(String(init!.body))).toEqual({ email: USER.email, password: "uma-password-boa" });
  });

  it("mostra o erro do servidor num alerta e leva o foco até ele", async () => {
    mockFetch({
      "/api/auth/login": new Response('{"detail":"Email ou password incorretos."}', { status: 401 }),
    });
    renderLogin();
    await userEvent.type(screen.getByLabelText("Email"), USER.email);
    await userEvent.type(screen.getByLabelText("Password"), "errada-errada");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Email ou password incorretos.");
    expect(alert).toHaveFocus();
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  });

  it("no registo, valida o comprimento da password antes de enviar", async () => {
    const spy = mockFetch({});
    renderLogin();
    await userEvent.click(screen.getByRole("button", { name: "Criar conta" }));
    const pw = screen.getByLabelText("Password");
    expect(pw).toHaveAttribute("autocomplete", "new-password");
    expect(pw).toHaveAccessibleDescription("Pelo menos 10 caracteres.");
    await userEvent.type(screen.getByLabelText("Email"), USER.email);
    await userEvent.type(pw, "curta");
    await userEvent.click(screen.getByRole("button", { name: "Criar conta" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("pelo menos 10 caracteres");
    expect(spy.mock.calls.some(([u]) => String(u) === "/api/auth/register")).toBe(false);
  });
});

describe("AccountBar", () => {
  it("sem sessão, convida a entrar", async () => {
    mockFetch({});
    renderApp(<AccountBar />);
    expect(await screen.findByRole("link", { name: /Entrar/ })).toHaveAttribute("href", "/entrar");
  });

  it("com sessão, mostra o email e termina a sessão", async () => {
    const spy = mockFetch({ "/api/auth/me": USER, "/api/me/favorites": [], "/api/auth/logout": null });
    renderApp(<AccountBar />);
    expect(await screen.findByText(USER.email)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sair" }));
    expect(await screen.findByRole("link", { name: /Entrar/ })).toBeInTheDocument();
    expect(spy.mock.calls.some(([u, i]) => String(u) === "/api/auth/logout" && i?.method === "POST")).toBe(true);
  });
});

describe("Favoritas na análise", () => {
  const base = {
    "/api/auth/me": USER,
    "/api/stats": new Response("", { status: 503 }),
    "/api/analytics/lines": [line({ line_id: "4512" }), line({ line_id: "1717" })],
    "/api/analytics/heatmap": [],
    "/api/analytics/stops": [stop()],
  };

  it("marca uma linha com a estrela, anuncia a mudança e mostra-a em 'As minhas linhas'", async () => {
    const spy = mockFetch({ ...base, "/api/me/favorites": [], "/api/me/favorites/1717": null });
    renderApp(<AnalyticsPage />, { route: "/analytics" });
    const star = await screen.findByRole("button", { name: "Adicionar a linha 1717 às favoritas" });
    expect(star).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(star);
    // A estrela aparece na tabela e no cartão "As minhas linhas", ambas premidas.
    const pressed = await screen.findAllByRole("button", { name: "Remover a linha 1717 das favoritas" });
    expect(pressed).toHaveLength(2);
    pressed.forEach((b) => expect(b).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByText("Linha 1717 adicionada às favoritas.")).toBeInTheDocument();
    const card = screen.getByRole("region", { name: "As minhas linhas" });
    expect(within(card).getByRole("button", { name: "Linha 1717" })).toBeInTheDocument();
    expect(spy.mock.calls.some(([u, i]) => String(u) === "/api/me/favorites/1717" && i?.method === "PUT")).toBe(true);
  });

  it("se o servidor falhar, repõe o estado e avisa", async () => {
    mockFetch({
      ...base,
      "/api/me/favorites": [],
      "/api/me/favorites/1717": new Response('{"detail":"erro"}', { status: 500 }),
    });
    renderApp(<AnalyticsPage />, { route: "/analytics" });
    await userEvent.click(await screen.findByRole("button", { name: "Adicionar a linha 1717 às favoritas" }));
    await waitFor(() =>
      expect(screen.getByText("Não foi possível atualizar a linha 1717. Tente novamente.")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Adicionar a linha 1717 às favoritas" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("sem sessão não há estrelas nem cartão de favoritas", async () => {
    mockFetch({ ...base, "/api/auth/me": new Response("", { status: 401 }) });
    renderApp(<AnalyticsPage />, { route: "/analytics" });
    await screen.findByRole("button", { name: "4512" });
    expect(screen.queryByRole("button", { name: /favoritas/ })).toBeNull();
    expect(screen.queryByRole("region", { name: "As minhas linhas" })).toBeNull();
  });
});
