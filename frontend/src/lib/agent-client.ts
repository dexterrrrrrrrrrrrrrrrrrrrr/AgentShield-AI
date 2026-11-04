export async function agentApi(path: string, method = "GET", body?: unknown) {
  const headers: Record<string, string> = {};
  try {
    if (method !== "GET") {
      const response = await fetch("/api/auth/csrf", {
        cache: "no-store",
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok)
        throw new Error("Session verification failed. Sign in again.");
      headers["X-CSRF-Token"] = (await response.json()).csrf_token;
      headers["Content-Type"] = "application/json";
    }
    const response = await fetch(`/api/agent${path}`, {
      method,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      signal: AbortSignal.timeout(95000),
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(
        data?.detail || "Agent service unavailable. Please retry.",
      );
    }
    return response.status === 204 ? null : response.json();
  } catch (cause) {
    throw new Error(
      cause instanceof Error &&
      cause.name !== "AbortError" &&
      cause.name !== "TimeoutError"
        ? cause.message
        : "Agent request timed out. Please retry.",
      { cause },
    );
  }
}
