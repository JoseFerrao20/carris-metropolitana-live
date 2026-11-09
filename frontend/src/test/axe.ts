import axe, { type Result } from "axe-core";

/** Regras WCAG 2.1 A/AA. O contraste de cor não é calculável no jsdom: é testado no Playwright. */
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"];

function describe(violations: Result[]): string {
  return violations
    .map((v) => `\n• [${v.impact}] ${v.id}: ${v.help}\n  ${v.nodes.map((n) => n.html).slice(0, 3).join("\n  ")}`)
    .join("");
}

export async function expectNoAxeViolations(
  node: Element,
  { isolated = false }: { isolated?: boolean } = {},
): Promise<void> {
  const rules: Record<string, { enabled: boolean }> = { "color-contrast": { enabled: false } };
  // Um componente renderizado sozinho não tem landmarks nem <h1>: essas regras só se aplicam às páginas.
  if (isolated) {
    rules.region = { enabled: false };
    rules["page-has-heading-one"] = { enabled: false };
    rules["landmark-one-main"] = { enabled: false };
  }
  const result = await axe.run(node, { runOnly: { type: "tag", values: TAGS }, rules });
  if (result.violations.length) throw new Error(`Violações de acessibilidade:${describe(result.violations)}`);
}
