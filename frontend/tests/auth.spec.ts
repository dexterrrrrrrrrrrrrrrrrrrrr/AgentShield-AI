import { test, expect, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

const password = "browser test passphrase only";
async function registerViaApi(
  page: Page,
  email: string,
  fullName = "Browser User",
) {
  const csrf = await page.request.get("/api/auth/csrf");
  const response = await page.request.post("/api/auth/register", {
    headers: {
      Origin: "http://localhost:3001",
      "X-CSRF-Token": (await csrf.json()).csrf_token,
    },
    data: { full_name: fullName, email, password, confirm_password: password },
  });
  expect(response.status()).toBe(201);
}
async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL("http://localhost:3001/");
  await expect(
    page.getByRole("heading", { name: "Dashboard overview" }),
  ).toBeVisible();
}

test("unauthenticated dashboard and profile redirect; API rejects missing auth and CSRF", async ({
  page,
}) => {
  for (const path of ["/", "/profile"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login$/);
    await expect(
      page.getByRole("heading", { name: "Welcome back" }),
    ).toBeVisible();
  }
  expect((await page.request.get("/api/auth/me")).status()).toBe(401);
  const status = await page.evaluate(
    async () =>
      (
        await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: "nobody@example.com",
            password: "wrong",
          }),
        })
      ).status,
  );
  expect(status).toBe(403);
});

test("registration, password toggle, login, profile, preserved dashboard, mobile layout, and logout", async ({
  page,
  context,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const email = `browser-${randomUUID()}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Browser Example");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password").fill("a different passphrase");
  await page.getByRole("button", { name: "Show passwords" }).click();
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute(
    "type",
    "text",
  );
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Passwords must match." }),
  ).toHaveText("Passwords must match.");
  await page.getByLabel("Confirm password").fill(password);
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(page).toHaveURL(/\/login\?registered=1$/);
  await expect(
    page.getByText("Account created. Sign in to continue."),
  ).toBeVisible();
  await signIn(page, email);
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "Connected · FastAPI is healthy" }),
  ).toBeVisible();
  const cookies = await context.cookies();
  const session = cookies.find((c) => c.name === "agentshield_session");
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe("Lax");
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  expect(await page.evaluate(() => document.cookie)).not.toContain(
    "agentshield_session",
  );
  for (const section of ["Settings"]) {
    await page
      .getByRole("navigation")
      .getByRole("button", { name: section, exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: `${section} is coming in a future phase`,
        exact: true,
      }),
    ).toBeVisible();
  }
  await page.getByRole("button", { name: "Back to overview" }).click();
  await page.route("**/api/health", (route) => route.abort());
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "API unavailable" }),
  ).toBeVisible();
  await page.unroute("**/api/health");
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Connected" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("link", { name: /Browser Example · Profile/ }).click();
  await expect(page.getByRole("heading", { name: "Profile" })).toBeVisible();
  await expect(page.getByText(email, { exact: true })).toBeVisible();
  await expect(page.getByText("Authenticated", { exact: true })).toBeVisible();
  await expect(page.getByText(/\d{4}-\d{2}-\d{2} \(UTC\)/)).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get("/api/auth/me")).status()).toBe(401);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  expect(errors).toEqual([]);
});

test("safe duplicate registration and generic invalid login errors", async ({
  page,
}) => {
  const email = `duplicate-${randomUUID()}@example.com`;
  await registerViaApi(page, email);
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Duplicate User");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password").fill(password);
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Unable to register with these details" }),
  ).toHaveText("Unable to register with these details");
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("incorrect");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Invalid email or password" }),
  ).toHaveText("Invalid email or password");
  await expect(page).toHaveURL(/\/login$/);
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("separate browser users cannot see each other's profile", async ({
  browser,
}) => {
  const contexts = await Promise.all([
    browser.newContext({ baseURL: "http://localhost:3001" }),
    browser.newContext({ baseURL: "http://localhost:3001" }),
  ]);
  const pages = await Promise.all(contexts.map((c) => c.newPage()));
  const emails = [
    `first-${randomUUID()}@example.com`,
    `second-${randomUUID()}@example.com`,
  ];
  for (let i = 0; i < 2; i++) {
    await registerViaApi(pages[i], emails[i], `Browser User ${i}`);
    await signIn(pages[i], emails[i]);
    await pages[i].goto("/profile");
    await expect(pages[i].getByText(emails[i], { exact: true })).toBeVisible();
    await expect(
      pages[i].getByText(emails[1 - i], { exact: true }),
    ).toHaveCount(0);
  }
  await pages[0].getByRole("button", { name: "Sign out" }).click();
  await expect(pages[0]).toHaveURL(/\/login$/);
  expect((await pages[1].request.get("/api/auth/me")).status()).toBe(200);
  await Promise.all(contexts.map((c) => c.close()));
});

test("authentication network errors clear the loading state and allow retry", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Email address").fill("offline-test@example.com");
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.route("**/api/auth/csrf", (route) => route.abort());
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Unable to connect" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeEnabled();
  await page.unroute("**/api/auth/csrf");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Invalid email or password" }),
  ).toBeVisible();
});
