import { defineConfig } from "@playwright/test";

/** Synthetic, intercepted API data only. The production backend is never contacted. */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "midnight-usability.spec.ts",
  outputDir: "/tmp/hrms-midnight-usability",
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 4_000 },
  reporter: "list",
  use: {
    baseURL: process.env.HRMS_MIDNIGHT_BASE_URL ?? "http://127.0.0.1:18188",
    browserName: "chromium",
    viewport: { width: 1440, height: 1000 },
    timezoneId: "Asia/Kolkata",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: process.env.HRMS_MIDNIGHT_BASE_URL ? undefined : {
    command: "npm run build && npm run preview -- --host 127.0.0.1 --port 18188 --strictPort",
    url: "http://127.0.0.1:18188",
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
});
