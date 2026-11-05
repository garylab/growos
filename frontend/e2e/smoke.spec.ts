import { expect, test } from "@playwright/test";

// Requires a running stack (docker compose up) and APP_AUTH_TOKEN passed via E2E_TOKEN if auth is enabled.
test("app loads, creates a project and shows navigation", async ({ page }) => {
  await page.goto("/");
  if (process.env.E2E_TOKEN) {
    await page.getByPlaceholder("Access token").fill(process.env.E2E_TOKEN);
    await page.getByRole("button", { name: "Sign in" }).click();
  }
  const hasSetup = await page.getByText("Create a project").isVisible().catch(() => false);
  if (hasSetup) {
    await page.getByPlaceholder("Acme").fill("E2E Project");
    await page.getByRole("button", { name: "Create project" }).click();
  }
  await expect(page.getByRole("link", { name: "Growth Opportunities" })).toBeVisible();
  await page.getByRole("link", { name: "Integrations" }).click();
  await expect(page.getByText("SiteOne Crawler (bundled)")).toBeVisible();
});
