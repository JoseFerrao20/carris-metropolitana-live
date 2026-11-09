import { expect, test } from "@playwright/test";
import { mockApi } from "./mocks";

test("entrar, marcar uma favorita e filtrar o mapa por ela", async ({ page }) => {
  await mockApi(page);
  await page.goto("/analytics");
  await page.getByRole("link", { name: /Entrar para guardar/ }).click();
  await expect(page).toHaveURL(/\/entrar$/);

  await page.getByLabel("Email").fill("ana@exemplo.pt");
  await page.getByLabel("Password").fill("password-correta");
  await page.getByRole("button", { name: "Entrar" }).click();

  // Volta à página de onde veio, já com sessão.
  await expect(page).toHaveURL(/\/analytics$/);
  await expect(page.getByText("ana@exemplo.pt")).toBeVisible();

  await page.getByRole("button", { name: "Adicionar a linha 1717 às favoritas" }).click();
  await expect(page.getByRole("region", { name: "As minhas linhas" })).toContainText("Linha 1717");

  await page.getByRole("link", { name: /mapa ao vivo/ }).click();
  await expect(page.getByTestId("vehicles")).toHaveText("3");
  await page.getByLabel(/Só as minhas linhas \(1\)/).check();

  await page.getByRole("link", { name: /Análise de atrasos/ }).click();
  await page.getByRole("button", { name: "Sair" }).click();
  await expect(page.getByRole("link", { name: /Entrar para guardar/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "As minhas linhas" })).toHaveCount(0);
});

test("o formulário de entrada usa-se só com teclado", async ({ page }) => {
  await mockApi(page);
  await page.goto("/entrar");
  await page.keyboard.press("Tab"); // primeiro elemento focável: o campo de email
  await expect(page.getByLabel("Email")).toBeFocused();
  await page.keyboard.type("ana@exemplo.pt");
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Password")).toBeFocused();
  await page.keyboard.type("errada-errada");
  await page.keyboard.press("Enter");
  // O erro recebe o foco, para ser anunciado e o utilizador saber onde está.
  await expect(page.getByRole("alert")).toBeFocused();
  await expect(page.getByRole("alert")).toHaveText("Email ou password incorretos.");
});
