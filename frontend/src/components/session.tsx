"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { authPost, type User } from "@/lib/auth-client";
import { SESSION_EXPIRED_EVENT, sessionExpired } from "@/lib/protected-api";

const UserContext = createContext<{
  user: User;
  active: boolean;
  beginLogout: () => void;
  cancelLogout: () => void;
} | null>(null);

export function SessionProvider({
  user,
  children,
}: {
  user: User;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [active, setActive] = useState(true);
  useEffect(() => {
    let live = true;
    let checking = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    function ended() {
      setActive(false);
      router.replace("/login");
      router.refresh();
    }
    function schedule(expires?: string, retry = false) {
      clearTimeout(timer);
      if (!expires && !retry) return;
      const delay = retry
        ? 30000
        : Math.max(1000, new Date(expires!).getTime() - Date.now() + 250);
      if (Number.isFinite(delay))
        timer = setTimeout(() => void check(), Math.min(delay, 2147483647));
    }
    async function check() {
      if (!live || !active || checking) return;
      checking = true;
      try {
        const response = await fetch("/api/auth/me", {
          cache: "no-store",
          credentials: "same-origin",
          signal: AbortSignal.timeout(5000),
        });
        if (!live) return;
        if (response.status === 401) ended();
        else if (response.ok) {
          const current: User = await response.json();
          // A cookie changed to another account: reload its server-protected view.
          if (current.id !== user.id) window.location.replace("/");
          else
            schedule(
              current.session_expires_at,
              !!current.session_expires_at &&
                new Date(current.session_expires_at).getTime() <= Date.now(),
            );
        } else schedule(undefined, true);
      } catch {
        if (live) schedule(undefined, true); // Network failure is not a revocation.
      } finally {
        checking = false;
      }
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, ended);
    window.addEventListener("focus", check);
    window.addEventListener("pageshow", check);
    if (active) void check();
    return () => {
      live = false;
      clearTimeout(timer);
      window.removeEventListener(SESSION_EXPIRED_EVENT, ended);
      window.removeEventListener("focus", check);
      window.removeEventListener("pageshow", check);
    };
  }, [router, user.id, active]);
  return (
    <UserContext
      value={{
        user,
        active,
        beginLogout: () => setActive(false),
        cancelLogout: () => setActive(true),
      }}
    >
      {children}
    </UserContext>
  );
}

export function useSession() {
  const value = useContext(UserContext);
  if (!value) throw new Error("Missing authenticated session context");
  return value;
}
export function useUser(): User {
  return useSession().user;
}

export function LogoutButton() {
  const { beginLogout, cancelLogout } = useSession();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function logout() {
    setLoading(true);
    setError("");
    beginLogout();
    try {
      await authPost("logout");
      sessionExpired();
    } catch (cause) {
      const response = await fetch("/api/auth/me", {
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      }).catch(() => null);
      if (response?.status === 401) sessionExpired();
      else {
        cancelLogout();
        setError(
          cause instanceof Error
            ? cause.message
            : "Unable to sign out. Please try again.",
        );
      }
    } finally {
      setLoading(false);
    }
  }
  return (
    <div>
      <button
        onClick={logout}
        disabled={loading}
        className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:border-teal-300 disabled:opacity-50"
      >
        {loading ? "Signing out…" : "Sign out"}
      </button>
      {error && (
        <p role="alert" className="mt-2 max-w-xs text-sm text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
