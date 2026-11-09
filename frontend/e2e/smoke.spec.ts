import { expect, test } from "@playwright/test";
import { mockApi } from "./mocks";

test("mapa ao vivo: recebe o snapshot por SSE e desenha os veículos", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByTestId("vehicles")).toHaveText("3");
  await expect(page.getByRole("status")).toContainText(/ligado|a religar/);
  await expect(page.locator(".map canvas")).toBeVisible();
  await page.getByPlaceholder(/Filtrar por linha/).fill("1717");
  await page.getByRole("link", { name: /Análise de atrasos/ }).click();
  await expect(page).toHaveURL(/\/analytics$/);
  expect(errors).toEqual([]);
});

test("análise: KPIs, heatmap, ranking e gráfico por paragem", async ({ page }) => {
  await mockApi(page);
  await page.goto("/analytics");
  await expect(page.getByText("72 / 149 ms")).toBeVisible();
  await expect(page.getByLabel(/Qui 10h/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Atraso médio por paragem: linha 4512" })).toBeVisible();
  await page.getByRole("button", { name: "1717" }).click();
  await expect(page.getByRole("img", { name: /linha 1717/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /linha 1717/ }).locator("rect")).toHaveCount(3);
});
