export async function monitoringApi(path: string, body?: unknown) {
  const headers: Record<string, string> = {};
  if (body) {
    const csrf = await fetch("/api/auth/csrf", {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    if (!csrf.ok) throw new Error("Authentication required");
    headers["X-CSRF-Token"] = (await csrf.json()).csrf_token;
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`/api${path}`, {
    method: body ? "POST" : "GET",
    headers,
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
    credentials: "same-origin",
    signal: AbortSignal.timeout(body ? 95000 : 10000),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Monitoring request failed",
    );
  return data;
}
