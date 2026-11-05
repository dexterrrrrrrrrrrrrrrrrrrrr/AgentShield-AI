import { defineConfig } from "@playwright/test";
import { randomBytes, randomUUID } from "node:crypto";

const uri = process.env.TEST_MONGODB_URI || "mongodb://127.0.0.1:27017";
if (!/^mongodb:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/?$/.test(uri))
  throw new Error("Browser tests require credential-free local MongoDB");
process.env.E2E_DATABASE =
  "agentshield_e2e_" + randomUUID().replaceAll("-", "");
process.env.E2E_MONGODB_URI = uri;
const python = process.env.BACKEND_PYTHON || "../backend/.venv/bin/python";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  expect: { timeout: 10000 },
  retries: 0,
  globalTeardown: "./tests/teardown.ts",
  use: {
    baseURL: "http://localhost:3001",
    trace: "retain-on-failure",
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    },
  },
  webServer: [
    {
      command: `${python} -m uvicorn scripts.browser_test_app:make_app --factory --app-dir ../backend --host 127.0.0.1 --port 8001 --no-proxy-headers --ws websockets --ws-max-size 1024 --ws-max-queue 8`,
      url: "http://127.0.0.1:8001/ready",
      timeout: 30000,
      env: {
        APP_ENV: "test",
        MONGODB_URI: uri,
        MONGODB_DATABASE: process.env.E2E_DATABASE,
        JWT_SECRET: randomBytes(48).toString("base64url"),
        CORS_ORIGINS: "http://localhost:3001",
        LOGIN_IP_LIMIT: "100",
        // Larger deterministic journey suite; production defaults and backend
        // rate-limit regression tests remain unchanged.
        REGISTER_IP_LIMIT: "30",
      },
    },
    {
      command: "npm run build && npm start -- --port 3001",
      url: "http://localhost:3001/login",
      timeout: 120000,
      env: {
        API_INTERNAL_URL: "http://127.0.0.1:8001",
        NEXT_PUBLIC_API_URL: "",
      },
    },
  ],
});
