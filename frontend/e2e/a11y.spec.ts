import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mockApi, type MockOptions } from "./mocks";

/**
 * Acessibilidade no browser real (WCAG 2.1 A/AA), incluindo contraste de cor, que o jsdom
 * não calcula. Corre em modo claro e escuro, porque as cores mudam entre os dois.
 */
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(TAGS)
    // O canvas WebGL e os controlos do MapLibre são de terceiros; o resto da página é analisado.
    .exclude(".maplibregl-canvas-container")
    .exclude(".maplibregl-control-container")
    .analyze();
  const summary = results.violations.map(
    (v) => `[${v.impact}] ${v.id}: ${v.help}\n    ${v.nodes.map((n) => n.target.join(" ")).slice(0, 5).join("\n    ")}`,
  );
  expect(summary, summary.join("\n")).toEqual([]);
}

const PAGES: Array<{ name: string; path: string; ready: (p: Page) => Promise<void>; opts?: MockOptions }> = [
  { name: "mapa", path: "/", ready: (p) => expect(p.getByTestId("vehicles")).toHaveText("3") },
  {
    name: "mapa com sessão e favoritas",
    path: "/",
    opts: { user: { id: 1, email: "ana@exemplo.pt" }, favorites: ["1717"] },
    ready: (p) => expect(p.getByLabel(/Só as minhas linhas/)).toBeVisible(),
  },
  {
    name: "análise",
    path: "/analytics",
    ready: (p) => expect(p.getByRole("img", { name: /Atraso médio por paragem/ })).toBeVisible(),
  },
  {
    name: "análise com sessão e favoritas",
    path: "/analytics",
    opts: { user: { id: 1, email: "ana@exemplo.pt" }, favorites: ["1717"] },
    ready: (p) => expect(p.getByRole("region", { name: "As minhas linhas" })).toBeVisible(),
  },
  { name: "entrar", path: "/entrar", ready: (p) => expect(p.getByLabel("Email")).toBeVisible() },
];

for (const scheme of ["light", "dark"] as const) {
  test.describe(`acessibilidade (${scheme === "light" ? "modo claro" : "modo escuro"})`, () => {
    test.use({ colorScheme: scheme });

    for (const pg of PAGES) {
      test(pg.name, async ({ page }) => {
        await mockApi(page, pg.opts);
        await page.goto(pg.path);
        await pg.ready(page);
        await expectAccessible(page);
      });
    }

    test("formulário de entrada com erro", async ({ page }) => {
      await mockApi(page);
      await page.goto("/entrar");
      await page.getByLabel("Email").fill("ana@exemplo.pt");
      await page.getByLabel("Password").fill("errada-errada");
      await page.getByRole("button", { name: "Entrar" }).click();
      await expect(page.getByRole("alert")).toBeVisible();
      await expectAccessible(page);
    });
  });
}
