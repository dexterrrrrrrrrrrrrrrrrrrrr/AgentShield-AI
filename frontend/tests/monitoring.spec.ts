import { test, expect, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

async function post(page: Page, path: string, data: unknown) {
  const csrf = await page.request.get("/api/auth/csrf");
  return page.request.post(path, {
    headers: {
      Origin: "http://localhost:3001",
      "X-CSRF-Token": (await csrf.json()).csrf_token,
    },
    data,
  });
}

test("real WebSocket monitoring, stored analytics, authorized approval rejection and reconnect", async ({
  page,
  browser,
}) => {
  const email = `monitor-${randomUUID()}@example.com`;
  expect(
    (
      await post(page, "/api/auth/register", {
        full_name: "Monitor Tester",
        email,
        password: "monitoring passphrase 123",
        confirm_password: "monitoring passphrase 123",
      })
    ).status(),
  ).toBe(201);
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page
    .getByLabel("Password", { exact: true })
    .fill("monitoring passphrase 123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Dashboard overview" }),
  ).toBeVisible();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Security Monitoring", exact: true })
    .click();
  await expect(page).toHaveURL(/\/monitoring$/);
  await expect(page.getByRole("status")).toHaveText("Live");
  const created = await post(page, "/api/agent/sessions", {
    provider: "groq",
    model: "llama-3.1-8b-instant",
    allowed_tools: ["calculator", "python_sandbox"],
  });
  expect(created.status()).toBe(201);
  const sid = (await created.json()).id;
  expect(
    (
      await post(page, `/api/agent/sessions/${sid}/messages`, {
        content: "Calculate 12+8",
      })
    ).status(),
  ).toBe(200);
  const timeline = page.getByRole("list", { name: "Activity timeline" });
  await expect(
    timeline.getByText("agent completed", { exact: true }),
  ).toBeVisible();
  await expect(
    timeline.getByText("tool requested", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(
    page
      .getByRole("heading", { name: "Total agent executions" })
      .locator("..")
      .getByText("1", { exact: true }),
  ).toBeVisible();
  const requested = await post(page, "/api/sandbox/execute", {
    code: 'print("monitor test")',
    agent_session_id: sid,
  });
  expect(requested.status()).toBe(200);
  await expect(
    timeline.getByText("approval required", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await page
    .getByRole("button", { name: "Review request", exact: true })
    .click();
  await expect(
    page
      .getByRole("region", { name: "Approval review" })
      .getByText('print("monitor test")', { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Reject request", exact: true })
    .click();
  await expect(
    timeline.getByText("tool rejected", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByRole("status")).toHaveText("Live");
  await expect(
    timeline.getByText("agent completed", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("list", { name: "Approval history" })
      .getByText(/rejected · rejected/),
  ).toBeVisible();
  const other = await browser.newContext({ baseURL: "http://localhost:3001" });
  const otherPage = await other.newPage();
  const otherEmail = `other-${randomUUID()}@example.com`;
  expect(
    (
      await post(otherPage, "/api/auth/register", {
        full_name: "Other User",
        email: otherEmail,
        password: "monitoring passphrase 123",
        confirm_password: "monitoring passphrase 123",
      })
    ).status(),
  ).toBe(201);
  await otherPage.goto("/login");
  await otherPage.getByLabel("Email address").fill(otherEmail);
  await otherPage
    .getByLabel("Password", { exact: true })
    .fill("monitoring passphrase 123");
  await otherPage.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(otherPage).toHaveURL("http://localhost:3001/");
  await otherPage.goto("/monitoring");
  await expect(otherPage.getByRole("status")).toHaveText("Live");
  await expect(
    otherPage.getByRole("list", { name: "Activity timeline" }).locator("li"),
  ).toHaveCount(0);
  await other.close();
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("monitoring shows snapshot errors and recovers on refresh", async ({
  page,
}) => {
  const email = `monitor-error-${randomUUID()}@example.com`;
  expect(
    (
      await post(page, "/api/auth/register", {
        full_name: "Monitor Error Tester",
        email,
        password: "monitoring passphrase 123",
        confirm_password: "monitoring passphrase 123",
      })
    ).status(),
  ).toBe(201);
  expect(
    (
      await post(page, "/api/auth/login", {
        email,
        password: "monitoring passphrase 123",
      })
    ).status(),
  ).toBe(200);
  let fail = true;
  await page.route("**/api/monitor/summary*", async (route) => {
    if (fail)
      await route.fulfill({
        status: 503,
        json: { detail: "Database temporarily unavailable" },
      });
    else await route.continue();
  });
  await page.goto("/monitoring");
  await expect(page.getByRole("main").getByRole("alert")).toHaveText(
    "Database temporarily unavailable",
  );
  await expect(page.getByText("Loading stored analytics…")).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  await expect(
    page
      .getByRole("heading", { name: "Total agent executions" })
      .locator("..")
      .getByText("0", { exact: true }),
  ).toBeVisible();
});
