export type User = {
  id: string;
  full_name: string;
  email: string;
  created_at: string;
  authenticated: boolean;
  session_expires_at?: string;
  email_verified?: boolean;
  profile_picture?: string | null;
  authentication_provider?: "password" | "google" | "password+google";
  google_connected?: boolean;
  last_login_at?: string | null;
};

async function authRequest(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, { ...init, signal: AbortSignal.timeout(10000) });
  } catch {
    throw new Error("Unable to connect. Please try again.");
  }
}

export async function authPost(
  path: "login" | "register" | "logout" | "google/start",
  payload?: unknown,
) {
  for (let attempt = 0; attempt < 2; attempt++) {
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
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf_token,
      },
      body: payload ? JSON.stringify(payload) : undefined,
    });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      if (
        attempt === 0 &&
        response.status === 403 &&
        data?.detail === "CSRF validation failed"
      )
        continue;
      throw new Error(
        typeof data?.detail === "string"
          ? data.detail
          : "Request failed. Please try again.",
      );
    }
    return response;
  }
  throw new Error("CSRF validation failed");
}

export async function googleAvailable(): Promise<boolean> {
  const response = await authRequest("/api/auth/providers", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) throw new Error("Unable to check Google sign-in availability.");
  const data = await response.json();
  return data?.google?.enabled === true;
}

export async function startGoogle(mode: "login" | "link"): Promise<void> {
  const response = await authPost("google/start", { mode });
  const data = await response.json();
  let target: URL;
  try {
    if (typeof data.authorization_url !== "string") throw new Error();
    target = new URL(data.authorization_url);
    if (
      target.origin !== "https://accounts.google.com" ||
      target.pathname !== "/o/oauth2/v2/auth" ||
      target.username || target.password || target.hash
    ) throw new Error();
  } catch {
    throw new Error("Unable to start Google sign-in safely. Please try again.");
  }
  window.location.assign(target.href);
}

const oauthMessages: Record<string, string> = {
  unavailable: "Google sign-in is not configured. Use email and password or contact your administrator.",
  cancelled: "Google sign-in was cancelled. You can try again or use email and password.",
  invalid_response: "Google sign-in could not be verified. Please start again.",
  expired_request: "This Google sign-in request expired or was already used. Please start again.",
  account_conflict: "An account already uses this email. Sign in to that account, then connect Google from Profile.",
  already_linked: "This Google account is already connected. Sign in to its existing account.",
  session_expired: "Your session expired. Sign in again before connecting Google.",
  temporarily_unavailable: "Google sign-in is temporarily unavailable. Please try again later.",
};

export function oauthErrorMessage(code?: string): string {
  if (!code) return "";
  return Object.hasOwn(oauthMessages, code)
    ? oauthMessages[code]
    : "Google sign-in could not be completed. Please start again.";
}
