import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";
import { randomUUID } from "node:crypto";

// Real auth/API/MongoDB/WebSockets; only the dedicated browser-test model and
// container adapters are mocked. Transport interruptions are explicitly routed.
const password = "phase seven browser test passphrase";

async function post(page: Page, path: string, data?: unknown) {
  const csrf = await page.request.get("/api/auth/csrf");
  expect(csrf.ok()).toBe(true);
  return page.request.post(path, {
    headers: {
      Origin: "http://localhost:3001",
      "X-CSRF-Token": (await csrf.json()).csrf_token,
    },
    data,
  });
}

async function signIn(page: Page) {
  const email = `phase7-${randomUUID()}@example.com`;
  expect(
    (
      await post(page, "/api/auth/register", {
        full_name: "Phase Seven Tester",
        email,
        password,
        confirm_password: password,
      })
    ).status(),
  ).toBe(201);
  expect(
    (await post(page, "/api/auth/login", { email, password })).status(),
  ).toBe(200);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Dashboard overview" }),
  ).toBeVisible();
  return email;
}

async function createSession(page: Page) {
  const response = await post(page, "/api/agent/sessions", {
    provider: "groq",
    model: "llama-3.1-8b-instant",
    allowed_tools: ["calculator"],
  });
  expect(response.status()).toBe(201);
  return (await response.json()).id as string;
}

async function send(page: Page, sid: string) {
  const response = await post(page, `/api/agent/sessions/${sid}/messages`, {
    content: "Calculate (12+8)/2",
  });
  expect(response.status()).toBe(200);
  expect((await response.json()).status).toBe("completed");
}

function timeline(page: Page) {
  return page.getByRole("list", { name: "Activity timeline" });
}

test("settings and tool configuration use real metadata, denied calls are audited, and deletion requires confirmation", async ({
  page,
}) => {
  await signIn(page);
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Settings", exact: true })
    .click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(
    page.getByRole("heading", { name: "Workspace settings", exact: true }),
  ).toBeVisible();
  const metadata = await (
    await page.request.get("/api/agent/providers")
  ).json();
  await expect(
    page.getByText(metadata.providers[0].model, { exact: true }).first(),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Workspace navigation" })
    .getByRole("link", { name: "Playground", exact: true })
    .click();
  const permissions = page.getByRole("group", { name: "Tool permissions" });
  for (const name of ["calculator", "summarize_text", "python_sandbox"])
    await permissions.getByRole("checkbox", { name, exact: true }).uncheck();
  await permissions
    .getByRole("checkbox", { name: "format_json", exact: true })
    .check();
  await page
    .getByLabel("Task or instructions")
    .fill("Calculate 12+8 despite the disabled calculator");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "unknown, unauthorized, or invalid tool" }),
  ).toBeVisible();
  const sessions = (
    await (await page.request.get("/api/agent/sessions")).json()
  ).sessions;
  expect(sessions).toHaveLength(1);
  expect(sessions[0].allowed_tools).toEqual(["format_json"]);
  await expect(
    permissions.getByRole("checkbox", { name: "calculator", exact: true }),
  ).toBeDisabled();
  await page.goto("/");
  await expect(
    page
      .getByRole("heading", { name: "Agent executions", exact: true })
      .locator("..")
      .getByText("1", { exact: true }),
  ).toBeVisible();
  await page.goto("/monitoring");
  await expect(
    timeline(page).getByText("tool rejected", { exact: true }),
  ).toBeVisible();
  await page.goto(`/playground?session=${sessions[0].id}`);
  await expect(
    page.getByRole("button", { name: "Clear conversation", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Clear conversation", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Clear conversation?" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(dialog).toHaveCount(0);
  expect(
    (await (await page.request.get("/api/agent/sessions")).json()).sessions,
  ).toHaveLength(1);
  await page
    .getByRole("button", { name: "Clear conversation", exact: true })
    .click();
  await dialog
    .getByRole("button", { name: "Delete conversation", exact: true })
    .click();
  await expect(page.getByRole("button", { name: /groq ·/ })).toHaveCount(0);
  expect(
    (await (await page.request.get("/api/agent/sessions")).json()).sessions,
  ).toHaveLength(0);
});

test("a real WebSocket reconnects with a replay cursor and safely ignores duplicate frames", async ({
  page,
}) => {
  await signIn(page);
  const sockets: WebSocketRoute[] = [];
  const urls: string[] = [];
  await page.routeWebSocket("**/api/monitor/ws**", (socket) => {
    sockets.push(socket);
    urls.push(socket.url());
    const server = socket.connectToServer();
    socket.onClose(() => void server.close({ code: 1000 }));
    server.onClose(
      (code, reason) => void socket.close({ code: code || 1000, reason }),
    );
    server.onMessage((message) => {
      socket.send(message);
      const data = JSON.parse(
        typeof message === "string" ? message : message.toString(),
      );
      if (data.type === "event") socket.send(message);
    });
  });
  await page.goto("/monitoring");
  await expect(page.getByRole("status")).toHaveText("Live");
  const sid = await createSession(page);
  await send(page, sid);
  await expect(
    timeline(page).getByText("agent completed", { exact: true }),
  ).toHaveCount(1);
  await sockets[0].close({ code: 1012, reason: "Controlled test restart" });
  await expect.poll(() => urls.length).toBe(2);
  await expect(page.getByRole("status")).toHaveText("Live");
  expect(Number(new URL(urls[1]).searchParams.get("after"))).toBeGreaterThan(0);
  await send(page, sid);
  await expect(
    timeline(page).getByText("agent completed", { exact: true }),
  ).toHaveCount(2);
  const summary = await (await page.request.get("/api/monitor/summary")).json();
  expect(summary.agent_executions.successful).toBe(2);
});

test("an opaque WebSocket disconnect after real session revocation does not reconnect", async ({
  page,
}) => {
  await signIn(page);
  const sockets: WebSocketRoute[] = [];
  await page.routeWebSocket("**/api/monitor/ws**", (socket) => {
    sockets.push(socket);
    const server = socket.connectToServer();
    socket.onClose(() => void server.close({ code: 1000 }));
    // Hold the server's close frame to model a browser that only exposes 1006.
    server.onClose(() => {});
  });
  await page.goto("/monitoring");
  await expect(page.getByRole("status")).toHaveText("Live");
  expect((await post(page, "/api/auth/logout")).status()).toBe(204);
  await sockets[0].close({
    code: 1006,
    reason: "Controlled opaque disconnect",
  });
  await expect(page).toHaveURL(/\/login$/);
  await page.waitForTimeout(1200);
  expect(sockets).toHaveLength(1);
  expect((await page.request.get("/api/monitor/summary")).status()).toBe(401);
});

test("explicit sign out closes live monitoring without starting another socket", async ({
  page,
}) => {
  await signIn(page);
  const sockets: WebSocketRoute[] = [];
  await page.routeWebSocket("**/api/monitor/ws**", (socket) => {
    sockets.push(socket);
    socket.connectToServer();
  });
  await page.goto("/monitoring");
  await expect(page.getByRole("status")).toHaveText("Live");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.waitForTimeout(1200);
  expect(sockets).toHaveLength(1);
  expect((await page.request.get("/api/auth/me")).status()).toBe(401);
});

test("an explicit WebSocket authorization denial stops automatic retries", async ({
  page,
}) => {
  await signIn(page);
  let attempts = 0;
  await page.routeWebSocket("**/api/monitor/ws**", async (socket) => {
    attempts += 1;
    socket.send(JSON.stringify({ type: "connected", protocol: 1 }));
    await socket.close({
      code: 4403,
      reason: "Controlled authorization denial",
    });
  });
  await page.goto("/monitoring");
  await expect(page.getByRole("status")).toHaveText(
    "Monitoring authorization denied",
  );
  await page.waitForTimeout(1200);
  expect(attempts).toBe(1);
});

test("agent sandbox approval resolves the same saved turn and produces the final response", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/playground");
  await page
    .getByRole("group", { name: "Tool permissions" })
    .getByRole("checkbox", { name: "python_sandbox", exact: true })
    .check();
  await page.getByLabel("Task or instructions").fill("sandbox phase7");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Review approval", exact: true }),
  ).toBeVisible();
  const sessions = (
    await (await page.request.get("/api/agent/sessions")).json()
  ).sessions;
  const sid = sessions[0].id;
  const before = (
    await (await page.request.get(`/api/agent/sessions/${sid}/messages`)).json()
  ).messages;
  expect(before).toHaveLength(1);
  expect(before[0].status).toBe("awaiting_approval");
  await page
    .getByRole("link", { name: "Review approval", exact: true })
    .click();
  const review = page.getByRole("region", { name: "Approval review" });
  await expect(
    review.getByText("print('phase7 approval')", { exact: true }),
  ).toBeVisible();
  await review
    .getByRole("button", { name: "Approve exact request", exact: true })
    .click();
  await expect(review).toHaveCount(0);
  await page.goto(`/playground?session=${sid}`);
  await page
    .getByRole("button", { name: "Continue after decision", exact: true })
    .click();
  await expect(
    page.getByText(
      "Mocked assistant confirmation: sandbox execution completed.",
      { exact: true },
    ),
  ).toBeVisible();
  const after = (
    await (await page.request.get(`/api/agent/sessions/${sid}/messages`)).json()
  ).messages;
  expect(after).toHaveLength(1);
  expect(after[0].id).toBe(before[0].id);
  expect(after[0].status).toBe("completed");
});

test("CSRF recovery retries once without duplicate side effects or retrying unrelated authorization denials", async ({
  page,
}) => {
  const email = await signIn(page);
  let loginAttempts = 0;
  await page.route("**/api/auth/login", async (route) => {
    loginAttempts += 1;
    if (loginAttempts === 1) {
      await route.fulfill({
        status: 403,
        json: { detail: "CSRF validation failed" },
      });
    } else {
      await route.continue();
    }
  });
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Dashboard overview" }),
  ).toBeVisible();
  expect(loginAttempts).toBe(2);

  let creationAttempts = 0;
  let mode = "recover";
  await page.route("**/api/agent/sessions", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    creationAttempts += 1;
    if (mode === "recover" && creationAttempts > 1) {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 403,
      json: {
        detail:
          mode === "forbidden"
            ? "Tool policy forbids this action"
            : "CSRF validation failed",
      },
    });
  });
  await page.goto("/playground");
  await page.getByLabel("Task or instructions").fill("Calculate (12+8)/2");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.getByText("Mocked assistant response: 10.", { exact: true }),
  ).toBeVisible();
  expect(creationAttempts).toBe(2);
  expect(
    (await (await page.request.get("/api/agent/sessions")).json()).sessions,
  ).toHaveLength(1);

  mode = "forbidden";
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await page.getByLabel("Task or instructions").fill("A new task");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Tool policy forbids this action" }),
  ).toBeVisible();
  expect(creationAttempts).toBe(3);

  mode = "exhausted";
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await page.getByLabel("Task or instructions").fill("Another task");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "CSRF validation failed" }),
  ).toBeVisible();
  expect(creationAttempts).toBe(5);
  expect(
    (await (await page.request.get("/api/agent/sessions")).json()).sessions,
  ).toHaveLength(1);
});

test("a silent monitoring connection is closed by the client watchdog and safely resumes its private replay", async ({
  page,
  browser,
}) => {
  await signIn(page);
  const sid = await createSession(page);
  await send(page, sid);

  const other = await browser.newContext({ baseURL: "http://localhost:3001" });
  const otherPage = await other.newPage();
  await signIn(otherPage);
  const foreignSid = await createSession(otherPage);
  await send(otherPage, foreignSid);
  await other.close();

  await page.clock.install();
  const urls: string[] = [];
  const closedCodes: number[] = [];
  let blackhole = false;
  let firstCompletedFrame = false;
  await page.routeWebSocket("**/api/monitor/ws**", (socket) => {
    const connectionNumber = urls.push(socket.url());
    const server = socket.connectToServer();
    socket.onClose((code) => {
      if (code !== undefined) closedCodes.push(code);
      void server.close({ code: 1000 });
    });
    server.onClose(
      (code, reason) => void socket.close({ code: code || 1000, reason }),
    );
    server.onMessage((message) => {
      if (connectionNumber === 1 && blackhole) return;
      socket.send(message);
      const data = JSON.parse(
        typeof message === "string" ? message : message.toString(),
      );
      if (
        connectionNumber === 1 &&
        data.type === "event" &&
        data.event.kind === "agent_completed"
      )
        firstCompletedFrame = true;
    });
  });
  await page.goto("/monitoring");
  await expect(page.getByRole("status")).toHaveText("Live");
  await expect.poll(() => firstCompletedFrame).toBe(true);
  await expect(
    timeline(page).getByText("agent completed", { exact: true }),
  ).toHaveCount(1);
  blackhole = true;
  await send(page, sid);

  // Browser virtual time advances; the real backend has not waited 35 seconds
  // for a missing pong. Recovery must therefore come from the client watchdog.
  await page.clock.fastForward(46000);
  await expect.poll(() => closedCodes.includes(4000)).toBe(true);
  await expect.poll(() => urls.length).toBe(2);
  expect(Number(new URL(urls[1]).searchParams.get("after"))).toBeGreaterThan(0);
  await expect(page.getByRole("status")).toHaveText("Live");
  await expect(
    timeline(page).getByText("agent completed", { exact: true }),
  ).toHaveCount(2);
  await expect(
    timeline(page).getByText(`Agent ${foreignSid.slice(0, 8)}`, {
      exact: false,
    }),
  ).toHaveCount(0);
  const sequence = (await timeline(page).locator("time").allTextContents()).map(
    (text) => Number(text.match(/#(\d+)/)?.[1]),
  );
  expect(sequence.every(Number.isSafeInteger)).toBe(true);
  expect(new Set(sequence).size).toBe(sequence.length);
  expect(
    sequence.every((seq, index) => index === 0 || sequence[index - 1] > seq),
  ).toBe(true);
});
