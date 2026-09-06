import { defineConfig } from "@playwright/test";
export default defineConfig({
  webServer: {
    command:
      "uv run uvicorn tradearena.api.main:app --host 127.0.0.1 --port 8765",
    url: "http://127.0.0.1:8765/health",
    reuseExistingServer: !process.env.CI,
    env: {
      DATABASE_URL: "sqlite:///./ui_preview.db",
      TRADEARENA_SECRET_KEY: "ui-preview-test-key-with-at-least-32-characters",
    },
  },
  testDir: "./tests/ui",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: {
    baseURL: "http://127.0.0.1:8765",
    browserName: "chromium",
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  reporter: [["list"], ["html", { open: "never" }]],
});
