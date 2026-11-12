import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:8888", headless: true,
    launchOptions: { executablePath: process.env.E2E_CHROMIUM_PATH },
  },
  reporter: "list",
});
