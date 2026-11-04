import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("mocked sandbox approval, output, history, and unavailable UI", async ({
  page,
}) => {
  const email = `sandbox-${randomUUID()}@example.com`;
  const csrf = await page.request.get("/api/auth/csrf");
  expect(
    (
      await page.request.post("/api/auth/register", {
        headers: {
          Origin: "http://localhost:3001",
          "X-CSRF-Token": (await csrf.json()).csrf_token,
        },
        data: {
          full_name: "Sandbox Tester",
          email,
          password: "a long sandbox passphrase",
          confirm_password: "a long sandbox passphrase",
        },
      })
    ).status(),
  ).toBe(201);
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page
    .getByLabel("Password", { exact: true })
    .fill("a long sandbox passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Dashboard overview" }),
  ).toBeVisible();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Sandbox", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Python Sandbox" }),
  ).toBeVisible();
  await page.getByLabel("Python code").fill('print("test")');
  await page.getByRole("button", { name: "Execute Python" }).click();
  await expect(
    page.getByRole("heading", { name: "Review exact execution request" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Approve exact request once" })
    .click();
  await expect(
    page.getByText("Mocked sandbox output", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve exact request once" }),
  ).toHaveCount(0);
  await page.reload();
  await page
    .getByRole("button", { name: /· completed/ })
    .first()
    .click();
  await expect(
    page.getByText("Mocked sandbox output", { exact: false }),
  ).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.route("**/api/sandbox/readiness", (route) =>
    route.fulfill({ json: { ready: false, code: "SANDBOX_UNAVAILABLE" } }),
  );
  await page.reload();
  await expect(page.getByRole("status")).toContainText("SANDBOX_UNAVAILABLE");
  await expect(
    page.getByRole("button", { name: "Execute Python" }),
  ).toBeDisabled();
});
