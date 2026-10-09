import { defineConfig } from "@playwright/test";

/** Celebration QA uses synthetic API fixtures; no backend or database is needed. */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "celebrations.spec.ts",
  outputDir: "/tmp/hrms-celebration-test-results",
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: "list",
  use: {
    baseURL: process.env.HRMS_CELEBRATIONS_BASE_URL ?? "http://127.0.0.1:18181",
    browserName: "chromium",
    viewport: { width: 1440, height: 1000 },
    timezoneId: "Asia/Kolkata",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: process.env.HRMS_CELEBRATIONS_BASE_URL ? undefined : {
    command: "npm run build && npm run preview -- --host 127.0.0.1 --port 18181 --strictPort",
    url: "http://127.0.0.1:18181",
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
});
