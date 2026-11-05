// Optional real-browser check of an isolated Compose stack; never calls a configured model.
import { createRequire } from "node:module";
import { randomBytes, randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const base = new URL(process.env.COMPOSE_BASE_URL || "http://localhost:3000");
if (!["localhost", "127.0.0.1", "[::1]"].includes(base.hostname) || !["http:", "https:"].includes(base.protocol) || base.username || base.password || base.pathname !== "/" || base.search || base.hash)
  throw new Error("Use an isolated credential-free loopback Compose origin");
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH });
const context = await browser.newContext({ baseURL: base.origin });
const page = await context.newPage();
const password = randomBytes(24).toString("base64url");
const email = `compose-browser-${randomUUID()}@example.com`;
try {
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Compose Browser Fixture");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password").fill(password);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard overview" })).toBeVisible();
  await page.goto("/playground");
  const providers = await (await page.request.get("/api/agent/providers")).json();
  let unconfigured = "SKIPPED: a model is configured, so no inference was requested";
  if (!providers.providers.find((p) => p.id === "groq")?.configured) {
    await page.getByLabel("Task or instructions").fill("Check the missing-provider setup message");
    await page.getByRole("button", { name: "Send message", exact: true }).click();
    await expect(page.getByText(/Groq is not configured/).first()).toBeVisible();
    await page.reload();
    await page.getByRole("button", { name: /groq ·/ }).first().click();
    await expect(page.getByText(/Groq is not configured/).first()).toBeVisible();
    unconfigured = "PASS: real setup failure and persisted history, without provider traffic";
  }
  await page.goto("/monitoring");
  await expect(page.getByRole("status")).toHaveText("Live");
  await page.getByRole("button", { name: "Sign out", exact: true }).first().click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/profile");
  await expect(page).toHaveURL(/\/login/);
  const report = {
    status: "PASS",
    integration: "Real browser against built Compose frontend and normal backend/MongoDB; no mocked providers or container adapters",
    registration_login_dashboard_logout: "PASS",
    protected_route_after_logout: "PASS",
    real_websocket: "PASS",
    missing_provider_and_history: unconfigured,
    live_inference: "SKIPPED: no configured model is invoked by this check",
    real_sandbox_execution: "SKIPPED: intentionally disabled in the public Compose backend",
    limitations: "Creates a disposable account in the selected isolated stack; no public TLS/Mac/resource-isolation claim",
  };
  if (process.env.COMPOSE_BROWSER_REPORT)
    await writeFile(process.env.COMPOSE_BROWSER_REPORT, JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report, null, 2));
} finally {
  await context.close();
  await browser.close();
}
