import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

// Real login; explicit mocked sandbox HTTP responses test the automatic-mode UI.
// Backend tests separately cover auth, policy, persistence and executor dispatch.
async function signIn(page: Page) {
  const email = `auto-${randomUUID()}@example.com`;
  const password = "auto browser validation passphrase";
  const { csrf_token } = await (await page.request.get("/api/auth/csrf")).json();
  const headers = { Origin: "http://localhost:3001", "X-CSRF-Token": csrf_token };
  expect((await page.request.post("/api/auth/register", { headers, data: {
    full_name: "Auto Tester", email, password, confirm_password: password,
  } })).status()).toBe(201);
  expect((await page.request.post("/api/auth/login", { headers, data: { email, password } })).status()).toBe(200);
  await page.route("**/api/sandbox/languages", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), execution_policy: "AUTO_EXECUTE" } });
  });
}

test("auto mode runs six languages with loading, output and history without approval controls", async ({ page }) => {
  await signIn(page);
  let executions: Record<string, unknown>[] = [];
  let release: () => void = () => {};
  let arrived: () => void = () => {};
  let approvals = 0;
  await page.route("**/api/sandbox/approvals/**", async (route) => { approvals++; await route.abort(); });
  await page.route("**/api/sandbox/executions?*", (route) => route.fulfill({ json: { executions } }));
  await page.route(/\/api\/sandbox\/executions\/[a-f0-9]+$/, (route) => route.fulfill({ json: executions[0] }));
  await page.route("**/api/sandbox/execute", async (route) => {
    const { language } = route.request().postDataJSON();
    expect(route.request().headers()["x-csrf-token"]).toBeTruthy();
    executions = [{ id: "c".repeat(32), language, status: "completed", policy_decision: "ALLOW",
      execution_policy: "AUTO_EXECUTE", stdout: "Hello World\n", stderr: "", exit_code: 0,
      execution_duration_ms: 15, compile_status: ["python", "javascript"].includes(language) ? "not_required" : "completed" }];
    const gate = new Promise<void>((resolve) => { release = resolve; });
    arrived();
    await gate;
    await route.fulfill({ json: executions[0] });
  });
  await page.goto("/sandbox");
  await expect(page.getByText(/Trusted local automatic execution/)).toBeVisible();
  for (const language of ["python", "c", "cpp", "java", "javascript", "typescript"]) {
    const requestArrived = new Promise<void>((resolve) => { arrived = resolve; });
    await page.getByLabel("Language", { exact: true }).selectOption(language);
    await page.getByRole("button", { name: "Run Code", exact: true }).click();
    await requestArrived;
    await expect(page.getByRole("button", { name: "Running...", exact: true })).toBeDisabled();
    await expect(page.getByRole("status")).toContainText("Running...");
    release();
    await expect(page.locator("article")).toContainText("Status: completed");
    await expect(page.locator("article")).toContainText("Exit code: 0");
    await expect(page.locator("article")).toContainText("15 ms");
    await expect(page.locator("article")).toContainText("Hello World");
    await expect(page.getByRole("button", { name: "Approve exact request once" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reject exact request", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Run Code", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Clear Output", exact: true }).click();
  }
  expect(approvals).toBe(0);
  await page.reload();
  await page.getByRole("button", { name: /· TypeScript · completed/ }).click();
  await expect(page.locator("article")).toContainText("Hello World");
});

test("auto mode stays disabled when readiness fails and shows submission failures", async ({ page }) => {
  await signIn(page);
  await page.route("**/api/sandbox/readiness*", (route) => route.fulfill({ json: { ready: false, code: "SANDBOX_UNAVAILABLE" } }));
  await page.goto("/sandbox");
  await expect(page.getByRole("status")).toContainText("SANDBOX_UNAVAILABLE");
  await expect(page.getByRole("button", { name: "Run Code", exact: true })).toBeDisabled();
  await page.route("**/api/sandbox/readiness*", (route) => route.fulfill({ json: { ready: true } }));
  await page.route("**/api/sandbox/execute", (route) => route.fulfill({ status: 503, json: { detail: "SANDBOX_UNAVAILABLE" } }));
  await page.getByRole("button", { name: "Refresh sandbox status" }).click();
  await page.getByRole("button", { name: "Run Code", exact: true }).click();
  await expect(page.locator("p[role=alert]")).toContainText("SANDBOX_UNAVAILABLE");
  await expect(page.locator("article")).toHaveCount(0);
});
