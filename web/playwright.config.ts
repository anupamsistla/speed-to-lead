import { defineConfig } from "@playwright/test";

const API_PORT = 8100;
const WEB_PORT = 5174;

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: [
    {
      // Real API with mock adapters and a rule-based stand-in for the model.
      command: `../.venv/bin/python ../scripts/e2e_server.py --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: !process.env.CI,
      stdout: "ignore",
      timeout: 30_000,
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { API_URL: `http://127.0.0.1:${API_PORT}`, WEB_PORT: String(WEB_PORT) },
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
});
