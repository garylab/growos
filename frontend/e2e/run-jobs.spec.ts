import { expect, test, type Page } from "@playwright/test";

const jobs = [
  ["crawl_domain", "free", "domain"], ["measure_performance", "free", "domain"],
  ["sync_search_console", "free", "domain"], ["sync_bing_webmaster", "free", "domain"],
  ["sync_analytics", "free", "domain"], ["build_growth_plan", "free", "project"],
  ["measure_outcomes", "free", "project"], ["snapshot_scorecard", "free", "project"],
  ["run_ai_visibility", "paid", "project"], ["suggest_keywords", "paid", "project"],
  ["suggest_competitors", "paid", "project"], ["suggest_prompts", "paid", "project"],
  ["sync_rankings", "paid", "project"], ["sync_keyword_metrics", "paid", "project"],
  ["sync_backlinks", "paid", "domain"], ["monitor_brand_mentions", "paid", "project"],
].map(([task_type, cost, scope]) => ({ task_type, label: task_type, cost, scope, default: cost === "free" }));

async function mockApp(page: Page, options: { active?: number; failCatalog?: boolean; empty?: boolean; failRun?: boolean; limited?: boolean; slow?: boolean } = {}) {
  const project = { id: "workflow-brand", slug: "mockreal", name: "MockReal", brand_name: "MockReal", settings: {}, brand_aliases: [], logo_version: null };
  const user = { id: "test-user", name: "Gary", email: "gary@example.com", role: "admin", is_active: true };
  const submitted: string[][] = [];
  let catalogRequests = 0;
  await page.addInitScript((user) => {
    localStorage.setItem("growos-app", JSON.stringify({ state: { token: "test-token", user, projectId: null, theme: "light" }, version: 0 }));
  }, user);
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    let data: unknown = [];
    if (path === "/meta") data = { auth_required: true };
    else if (path === "/auth/me") data = user;
    else if (path === "/projects") data = [project];
    else if (path === `/projects/${project.id}`) data = project;
    else if (path === "/notifications") data = { unread: 0, items: [] };
    else if (path.endsWith("/overview")) data = { project, seo: [], geo: { current: null, previous: null, runs_history: [] }, brand: { total: 0, mentions: {}, with_intent: 0 }, opportunities: { counts: {}, top: [] }, actions: { counts: {}, recent: [], outcomes: [] } };
    else if (path.endsWith("/jobs/activity")) data = { active: options.active ?? 0 };
    else if (path.endsWith("/scorecard")) data = null;
    else if (path.endsWith("/jobs/catalog")) {
      catalogRequests++;
      if (options.slow) await new Promise((resolve) => setTimeout(resolve, 700));
      if (options.failCatalog && catalogRequests === 1) { await route.fulfill({ status: 503, json: { detail: "Catalog unavailable" } }); return; }
      data = options.empty ? [] : options.limited ? jobs.filter((j) => ["crawl_domain", "build_growth_plan"].includes(j.task_type)) : jobs;
    } else if (path.endsWith("/jobs/run-selected")) {
      submitted.push(route.request().postDataJSON().task_types);
      if (options.failRun) { await route.fulfill({ status: 503, json: { detail: "Queue unavailable" } }); return; }
      data = { enqueued: submitted.at(-1), count: submitted.at(-1)!.length };
    }
    await route.fulfill({ json: data });
  });
  await page.goto("/mockreal/overview");
  if ((page.viewportSize()?.width ?? 1280) < 1024) await page.getByRole("button", { name: "Open menu" }).click();
  await page.getByRole("button", { name: options.active ? `Running (${options.active})` : "Run", exact: true }).click();
  return submitted;
}

test("workflow groups all available jobs and explains every paid job without selecting it", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1080 });
  const submitted = await mockApp(page);
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("region", { name: "Job workflow", exact: true })).toBeVisible();
  await expect(dialog.getByRole("heading", { level: 3 })).toHaveCount(4);
  await expect(dialog.getByRole("checkbox")).toHaveCount(16);
  await expect(dialog.locator('input[type="checkbox"]:checked')).toHaveCount(8);
  await expect(dialog.getByText("· 0 paid", { exact: false })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("workflow-desktop.png") });
  const explanations = [
    ["Suggest keywords", "saved Search Console and crawl data"],
    ["Suggest competitors", "saved AI citations"],
    ["Suggest AI prompts", "People Also Ask"],
    ["AI visibility sampling", "samples per prompt"],
    ["Keyword rankings", "each target keyword"],
    ["Keyword metrics", "does not buy ads"],
    ["Backlinks", "additional request"],
    ["Brand mentions", "Hacker News and Bluesky"],
  ];
  for (const [name, detail] of explanations) {
    await dialog.getByRole("button", { name: `Cost details for ${name}`, exact: true }).hover();
    await expect(page.getByRole("tooltip")).toContainText(detail);
    await expect(dialog.getByRole("checkbox", { name: new RegExp(`^${name}`) })).not.toBeChecked();
    await dialog.getByRole("heading", { name: "Run jobs", exact: true }).hover();
  }
  expect(submitted).toEqual([]);
});

test("runs only chosen jobs and resets paid choices when reopened", async ({ page }) => {
  const submitted = await mockApp(page);
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Select all", exact: true }).click();
  await expect(dialog.locator('input[type="checkbox"]:checked')).toHaveCount(16);
  await dialog.getByRole("button", { name: "Free only", exact: true }).click();
  await expect(dialog.locator('input[type="checkbox"]:checked')).toHaveCount(8);
  await dialog.getByRole("button", { name: "Clear all", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "Run 0 jobs", exact: true })).toBeDisabled();
  await dialog.getByRole("checkbox", { name: /^Website crawl/ }).check();
  await dialog.getByRole("checkbox", { name: /^Keyword rankings/ }).check();
  await expect(dialog.getByText("· 1 paid", { exact: false })).toBeVisible();
  await dialog.getByRole("button", { name: "Run 2 jobs", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(submitted).toEqual([["crawl_domain", "sync_rankings"]]);
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: /^Keyword rankings/ })).not.toBeChecked();
  await expect(page.getByRole("dialog").locator('input[type="checkbox"]:checked')).toHaveCount(8);
});

test.describe("mobile", () => {
test.use({ hasTouch: true });
test("workflow and cost tooltips stay inside the viewport and work by touch or keyboard", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApp(page);
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("checkbox", { name: /^Website crawl/ })).toBeVisible();
  expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await expect(dialog.getByRole("button", { name: "Run 8 jobs", exact: true })).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath("workflow-mobile.png") });
  const trigger = dialog.getByRole("button", { name: "Cost details for Keyword metrics", exact: true });
  await trigger.focus();
  await trigger.press("Enter");
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toContainText("does not buy ads");
  const box = (await tooltip.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
  expect(box.y + box.height).toBeLessThanOrEqual(844);
  await page.screenshot({ path: testInfo.outputPath("workflow-mobile-tooltip.png") });
  await expect(dialog.getByRole("checkbox", { name: /^Keyword metrics/ })).not.toBeChecked();
  await trigger.press("Enter");
  await expect(tooltip).toHaveCount(0);
  await trigger.tap();
  await expect(tooltip).toContainText("does not buy ads");
});
});

test("catalog loading, failure and retry do not look like an empty workflow", async ({ page }) => {
  await mockApp(page, { failCatalog: true, slow: true });
  await expect(page.getByRole("status")).toContainText("Loading available jobs");
  await expect(page.getByRole("alert")).toContainText("Could not load available jobs");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("checkbox")).toHaveCount(16);
});

test("only configured jobs are offered, including when stages are empty", async ({ page }) => {
  await mockApp(page, { limited: true });
  await expect(page.getByRole("checkbox")).toHaveCount(2);
  await expect(page.getByRole("button", { name: /^Cost details/ })).toHaveCount(0);
  await expect(page.getByText("No available jobs in this stage.")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Run 2 jobs" })).toBeEnabled();
});

test("an empty catalog cannot enqueue jobs", async ({ page }) => {
  const submitted = await mockApp(page, { empty: true });
  await expect(page.getByText("No runnable jobs.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run 0 jobs" })).toBeDisabled();
  expect(submitted).toEqual([]);
});

test("an enqueue failure keeps the workflow and selection available", async ({ page }) => {
  await mockApp(page, { failRun: true });
  await page.getByRole("button", { name: "Clear all", exact: true }).click();
  await page.getByRole("checkbox", { name: /^Suggest keywords/ }).check();
  await page.getByRole("button", { name: "Run 1 job", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Queue unavailable");
  await expect(page.getByRole("checkbox", { name: /^Suggest keywords/ })).toBeChecked();
  await expect(page.getByRole("button", { name: "Run 1 job", exact: true })).toBeEnabled();
});


test("running count updates and blocks starting jobs until all active jobs finish", async ({ page }) => {
  const activity = { active: 2 };
  const submitted = await mockApp(page, activity);
  const trigger = page.getByRole("button", { name: "Running (2)", exact: true });
  await expect(trigger).toBeVisible();
  await expect(trigger).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await expect(trigger.locator("svg")).toHaveCount(1);
  await expect(page.getByRole("status", { name: "Worker status" })).toHaveCount(0);
  const run = page.getByRole("dialog").getByRole("button", { name: "Running...", exact: true });
  await expect(run).toBeDisabled();
  activity.active = 1;
  await expect(page.getByRole("button", { name: "Running (1)", exact: true })).toBeVisible({ timeout: 10000 });
  await expect(run).toBeDisabled();
  activity.active = 0;
  await expect(page.getByRole("button", { name: "Run", exact: true })).toBeVisible({ timeout: 10000 });
  await expect(page.getByRole("dialog").getByRole("button", { name: "Run 8 jobs", exact: true })).toBeEnabled();
  expect(submitted).toEqual([]);
});
