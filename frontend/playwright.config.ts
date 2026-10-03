import { defineConfig } from "@playwright/test";
const db = process.env.HRMS_E2E_DATABASE_URL;
if (!db || !new URL(db).pathname.endsWith("_test")) {
  throw new Error("Browser tests require HRMS_E2E_DATABASE_URL pointing to an isolated *_test database");
}
export default defineConfig({
  testDir: "./e2e", workers: 1, timeout: 90_000,
  use: { baseURL: "http://127.0.0.1:18180", trace: "retain-on-failure",
    screenshot: "only-on-failure", timezoneId: "Asia/Kolkata",
    permissions: ["geolocation"], geolocation: { latitude: 12.97, longitude: 77.59 } },
  webServer: [
    { command: "cd ../backend && PYTHONPATH=src ${HRMS_E2E_PYTHON:-python} -m uvicorn hrms.main:app --host 127.0.0.1 --port 18015",
      url: "http://127.0.0.1:18015/health/ready", timeout: 60_000, reuseExistingServer: false,
      env: { HRMS_DATABASE_URL: db, HRMS_APP_DATABASE_URL: process.env.HRMS_E2E_APP_DATABASE_URL || db,
        HRMS_ENVIRONMENT: "local", HRMS_DEBUG: "false", HRMS_THROTTLE_ENABLED: "false",
        HRMS_SECRET_KEY: "synthetic-browser-test-signing-key-123456789",
        HRMS_CORS_ORIGINS: "http://127.0.0.1:18180", HRMS_STORAGE_DIR: "/tmp/hrms-e2e-storage" } },
    { command: "npm run build && npm run preview -- --host 127.0.0.1 --port 18180 --strictPort",
      url: "http://127.0.0.1:18180", timeout: 120_000, reuseExistingServer: false,
      env: { VITE_API_URL: "http://127.0.0.1:18015" } },
  ],
});
