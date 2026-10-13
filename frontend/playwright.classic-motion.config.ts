import { defineConfig } from "@playwright/test";

/** Motion QA uses intercepted synthetic API responses; no backend or database is needed. */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "classic-motion.spec.ts",
  outputDir: "/tmp/hrms-classic-motion-test-results",
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: "list",
  use: {
    baseURL: process.env.HRMS_CLASSIC_MOTION_BASE_URL ?? "http://127.0.0.1:18181",
    browserName: "chromium",
    timezoneId: "Asia/Kolkata",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: process.env.HRMS_CLASSIC_MOTION_REVIEW_VIDEO ? { mode: "on", size: { width: 1440, height: 1000 } } : "on",
  },
  webServer: process.env.HRMS_CLASSIC_MOTION_BASE_URL ? undefined : {
    command: "npm run build && npm run preview -- --host 127.0.0.1 --port 18181 --strictPort",
    url: "http://127.0.0.1:18181",
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
});
