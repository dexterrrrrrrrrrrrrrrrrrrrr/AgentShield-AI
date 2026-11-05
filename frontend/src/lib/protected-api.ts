export const SESSION_EXPIRED_EVENT = "agentshield:session-expired";

export function sessionExpired() {
  if (typeof window !== "undefined")
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Same-origin requests. Only a CSRF dependency rejection can be retried once;
 * it occurs before route side effects. Unknown execution outcomes are never retried. */
export async function protectedApi(
  path: string,
  method = "GET",
  body?: unknown,
  timeout = method === "GET" ? 10000 : 95000,
) {
  try {
    for (let attempt = 0; attempt < 2; attempt++) {
      const headers: Record<string, string> = {};
      if (method !== "GET") {
        const csrf = await fetch("/api/auth/csrf", {
          credentials: "same-origin",
          cache: "no-store",
          signal: AbortSignal.timeout(10000),
        });
        if (csrf.status === 401) sessionExpired();
        if (!csrf.ok)
          throw new ApiError(
            "Session verification unavailable. Please retry.",
            csrf.status,
          );
        headers["X-CSRF-Token"] = (await csrf.json()).csrf_token;
        if (body !== undefined) headers["Content-Type"] = "application/json";
      }
      const response = await fetch(`/api${path}`, {
        method,
        headers,
        credentials: "same-origin",
        cache: "no-store",
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(timeout),
      });
      if (response.status === 401) sessionExpired();
      if (response.status === 204) return null;
      const data = await response.json().catch(() => null);
      if (
        attempt === 0 &&
        method !== "GET" &&
        response.status === 403 &&
        data?.detail === "CSRF validation failed"
      )
        continue;
      if (!response.ok)
        throw new ApiError(
          typeof data?.detail === "string"
            ? data.detail
            : "Service unavailable. Please retry.",
          response.status,
        );
      if (data === null)
        throw new ApiError(
          "The service returned an invalid response. Please retry.",
          502,
        );
      return data;
    }
    throw new ApiError("CSRF validation failed", 403);
  } catch (cause) {
    if (cause instanceof ApiError) throw cause;
    throw new ApiError(
      cause instanceof Error &&
      (cause.name === "TimeoutError" || cause.name === "AbortError")
        ? "Request timed out. Check execution history before retrying."
        : "Unable to connect. Please try again.",
      0,
    );
  }
}
