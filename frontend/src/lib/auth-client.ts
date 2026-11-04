export type User = {
  id: string;
  full_name: string;
  email: string;
  created_at: string;
  authenticated: boolean;
};

async function authRequest(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, { ...init, signal: AbortSignal.timeout(10000) });
  } catch {
    throw new Error("Unable to connect. Please try again.");
  }
}

export async function authPost(
  path: "login" | "register" | "logout",
  payload?: unknown,
) {
  const csrf = await authRequest("/api/auth/csrf", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!csrf.ok) throw new Error("Unable to connect. Please try again.");
  const { csrf_token } = await csrf.json();
  const response = await authRequest(`/api/auth/${path}`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : "Request failed. Please try again.",
    );
  }
  return response;
}
