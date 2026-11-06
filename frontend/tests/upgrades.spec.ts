import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

// Real auth, policy, approvals, and MongoDB; browser_test_app explicitly mocks
// container processes. OAuth navigation/provider routes below are UI fixtures.
async function signIn(page: Page) {
  const email = `upgrade-${randomUUID()}@example.com`;
  const password = "upgrade browser test passphrase";
  const csrf = await (await page.request.get("/api/auth/csrf")).json();
  const headers = { Origin: "http://localhost:3001", "X-CSRF-Token": csrf.csrf_token };
  expect((await page.request.post("/api/auth/register", { headers, data: {
    full_name: "Upgrade Tester", email, password, confirm_password: password,
  } })).status()).toBe(201);
  expect((await page.request.post("/api/auth/login", { headers, data: { email, password } })).status()).toBe(200);
}

test("six registered language editors preserve drafts and compiled approval binds stdin through execution history", async ({ page }) => {
  await signIn(page);
  await page.goto("/sandbox");
  const selector = page.getByLabel("Language", { exact: true });
  await expect(selector.locator("option")).toHaveCount(6);
  for (const [value, label] of [["python", "Python"], ["c", "C"], ["cpp", "C++"], ["java", "Java"], ["javascript", "JavaScript"], ["typescript", "TypeScript"]]) {
    await selector.selectOption(value);
    await expect(page.getByLabel(`${label} code`, { exact: true })).not.toHaveValue("");
  }
  await selector.selectOption("c");
  const source = '#include <stdio.h>\nint main(void) { puts("browser compile fixture"); return 0; }';
  await page.getByLabel("C code", { exact: true }).fill(source);
  await page.getByLabel("Standard input (optional)").fill("owner-bound input");
  await selector.selectOption("python");
  await selector.selectOption("c");
  await expect(page.getByLabel("C code", { exact: true })).toHaveValue(source);
  await page.getByRole("button", { name: "Run Code", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Review exact execution request" })).toBeVisible();
  await expect(page.locator("article")).toContainText("Language: C.");
  await expect(page.locator("article pre").filter({ hasText: "owner-bound input" })).toBeVisible();
  const before = await (await page.request.get("/api/sandbox/executions?language=c")).json();
  expect(before.executions).toHaveLength(1);
  expect(before.executions[0].status).toBe("pending_approval");
  await page.getByRole("button", { name: "Approve exact request once" }).click();
  await expect(page.locator("article")).toContainText("Status: completed");
  await expect(page.locator("article")).toContainText("Compilation: completed");
  await expect(page.locator("article")).toContainText("Mocked compilation output");
  await expect(page.locator("article")).toContainText("owner-bound input");
  await page.getByRole("button", { name: "Clear Output", exact: true }).click();
  await expect(page.locator("article")).toHaveCount(0);
  await page.getByLabel("Filter by language").selectOption("c");
  await page.getByRole("button", { name: /· C · completed/ }).click();
  await expect(page.locator("article")).toContainText("Mocked sandbox output");
  await page.getByLabel("Filter by language").selectOption("java");
  await expect(page.getByText("No executions recorded.")).toBeVisible();
});

test("selected-language readiness failure disables execution and keeps drafts recoverable", async ({ page }) => {
  await signIn(page);
  await page.route("**/api/sandbox/readiness?language=javascript", (route) => route.fulfill({ json: {
    ready: false, code: "SANDBOX_UNAVAILABLE", message: "The selected runtime image is not provisioned.",
  } }));
  await page.goto("/sandbox");
  await page.getByLabel("Language", { exact: true }).selectOption("javascript");
  await expect(page.getByRole("status")).toContainText("SANDBOX_UNAVAILABLE");
  await expect(page.getByRole("button", { name: "Run Code", exact: true })).toBeDisabled();
  await expect(page.getByLabel("JavaScript code")).toHaveValue(/console.log/);
  await page.getByLabel("Language", { exact: true }).selectOption("python");
  await expect(page.getByRole("button", { name: "Run Code", exact: true })).toBeEnabled();
});

test("Google auth screens explain unavailable providers and safe callback conflicts", async ({ page }) => {
  await page.route("**/api/auth/providers", (route) => route.fulfill({ json: { google: { enabled: false } } }));
  await page.goto("/login?oauth_error=account_conflict");
  await expect(page.locator("p[role=alert]")).toContainText("Sign in to that account, then connect Google from Profile");
  await expect(page.getByRole("button", { name: "Continue with Google", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeEnabled();
  await page.getByText("Forgot password?", { exact: true }).click();
  await expect(page.getByText(/Password recovery is not available yet/)).toBeVisible();
  await page.goto("/register");
  await expect(page.getByRole("button", { name: "Continue with Google", exact: true })).toBeDisabled();
  await page.goto("/login?oauth_error=__proto__");
  await expect(page.locator("p[role=alert]")).toContainText("Google sign-in could not be completed");
  await expect(page.locator("p[role=alert]")).not.toContainText("__proto__");
});

test("Google start uses CSRF and fixed provider navigation; profile linking requires link mode", async ({ page }) => {
  await page.route("**/api/auth/providers", (route) => route.fulfill({ json: { google: { enabled: true } } }));
  const requests: Array<{ mode: string; csrf: string | undefined }> = [];
  const google = "https://accounts.google.com/o/oauth2/v2/auth?client_id=ui-fixture&response_type=code&state=ui-fixture";
  await page.route("**/api/auth/google/start", async (route) => {
    requests.push({ mode: route.request().postDataJSON().mode, csrf: route.request().headers()["x-csrf-token"] });
    await route.fulfill({ json: { authorization_url: google } });
  });
  await page.route("https://accounts.google.com/**", (route) => route.fulfill({ contentType: "text/plain", body: "Explicit mocked Google navigation destination" }));
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue with Google", exact: true }).click();
  await expect(page).toHaveURL(google);
  expect(requests[0].mode).toBe("login");
  expect(requests[0].csrf).toBeTruthy();
  await signIn(page);
  await page.goto("/profile");
  await expect(page.getByText("Not connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Connect Google account", exact: true }).click();
  await expect(page).toHaveURL(google);
  expect(requests[1].mode).toBe("link");
  expect(requests[1].csrf).toBeTruthy();
  await page.route("**/api/auth/google/start", (route) => route.fulfill({ json: { authorization_url: "https://untrusted.example/login" } }));
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue with Google", exact: true }).click();
  await expect(page.locator("p[role=alert]")).toContainText("Unable to start Google sign-in safely");
  await expect(page).toHaveURL(/\/login$/);
});

test("compiler errors remain failed executions with bounded diagnostic display", async ({ page }) => {
  await signIn(page);
  await page.goto("/sandbox");
  await page.getByLabel("Language", { exact: true }).selectOption("c");
  await page.getByLabel("C code", { exact: true }).fill("#error browser compile fixture");
  await page.getByRole("button", { name: "Run Code", exact: true }).click();
  await page.getByRole("button", { name: "Approve exact request once" }).click();
  await expect(page.locator("article")).toContainText("Status: failed");
  await expect(page.locator("article")).toContainText("Compilation: failed");
  await expect(page.locator("article")).toContainText("Mocked compiler diagnostic: invalid source");
  await expect(page.getByRole("button", { name: "Approve exact request once" })).toHaveCount(0);
});

test("language-aware agent tools keep exact human approval and original turn continuation", async ({ page }) => {
  await signIn(page);
  await page.goto("/playground");
  await page.getByLabel("Task or instructions").fill("sandbox multilang with approval");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.getByRole("link", { name: "Review approval", exact: true })).toBeVisible();
  const sessions = await (await page.request.get("/api/agent/sessions")).json();
  const sid = sessions.sessions[0].id;
  const history = await (await page.request.get(`/api/agent/sessions/${sid}/messages`)).json();
  const eid = history.messages[0].pending_execution_ids[0];
  await page.goto(`/monitoring?execution=${eid}`);
  const review = page.getByRole("region", { name: "Approval review" });
  await expect(review).toContainText("Language: C");
  await expect(review).toContainText("agent-bound input");
  await review.getByRole("button", { name: "Approve exact request", exact: true }).click();
  await page.goto(`/playground?session=${sid}`);
  await page.getByRole("button", { name: "Continue after decision", exact: true }).click();
  await expect(page.getByText("Mocked assistant confirmation: sandbox execution completed.", { exact: true })).toBeVisible();
  const result = await (await page.request.get(`/api/sandbox/executions/${eid}`)).json();
  expect(result.language).toBe("c");
  expect(result.status).toBe("completed");
  expect(result.compile_status).toBe("completed");
});
