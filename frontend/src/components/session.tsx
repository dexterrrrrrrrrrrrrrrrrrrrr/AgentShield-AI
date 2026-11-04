"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { authPost, type User } from "@/lib/auth-client";

const UserContext = createContext<User | null>(null);

export function SessionProvider({
  user,
  children,
}: {
  user: User;
  children: React.ReactNode;
}) {
  const router = useRouter();
  useEffect(() => {
    async function check() {
      try {
        const response = await fetch("/api/auth/me", {
          cache: "no-store",
          credentials: "same-origin",
          signal: AbortSignal.timeout(5000),
        });
        if (response.status === 401) {
          router.replace("/login");
          router.refresh();
        }
      } catch {
        /* A network outage does not imply a revoked session. */
      }
    }
    void check();
    window.addEventListener("focus", check);
    window.addEventListener("pageshow", check);
    return () => {
      window.removeEventListener("focus", check);
      window.removeEventListener("pageshow", check);
    };
  }, [router]);
  return <UserContext value={user}>{children}</UserContext>;
}

export function useUser(): User {
  const user = useContext(UserContext);
  if (!user) throw new Error("Missing authenticated session context");
  return user;
}

export function LogoutButton() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function logout() {
    setLoading(true);
    setError("");
    try {
      await authPost("logout");
      router.replace("/login");
      router.refresh();
    } catch (cause) {
      // If the session already expired, the server-protected route redirects safely.
      const response = await fetch("/api/auth/me", {
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      }).catch(() => null);
      if (response?.status === 401) {
        router.replace("/login");
        router.refresh();
      } else
        setError(
          cause instanceof Error
            ? cause.message
            : "Unable to sign out. Please try again.",
        );
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
