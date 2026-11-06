"use client";

import { useEffect, useState } from "react";
import { googleAvailable, startGoogle } from "@/lib/auth-client";

export default function GoogleButton({
  mode = "login",
  disabled = false,
  onBusy,
}: {
  mode?: "login" | "link";
  disabled?: boolean;
  onBusy?: (busy: boolean) => void;
}) {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    googleAvailable().then((enabled) => {
      if (live) setAvailable(enabled);
    }).catch(() => {
      if (live) {
        setAvailable(false);
        setError("Unable to check Google sign-in availability. Reload to try again.");
      }
    });
    return () => { live = false; };
  }, []);

  async function begin() {
    setBusy(true);
    onBusy?.(true);
    setError("");
    try {
      await startGoogle(mode);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to start Google sign-in.");
      setBusy(false);
      onBusy?.(false);
    }
  }

  return (
    <div>
      <button
        type="button"
        disabled={disabled || busy || available !== true}
        onClick={begin}
        aria-describedby="google-availability"
        className="flex w-full items-center justify-center gap-3 rounded-lg border border-slate-600 bg-white px-4 py-3 text-sm font-semibold text-slate-900 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-teal-300 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5">
          <path fill="#4285F4" d="M21.6 12.23c0-.71-.06-1.39-.18-2.05H12v3.88h5.38a4.6 4.6 0 0 1-1.99 3.02v2.51h3.22c1.89-1.74 2.99-4.3 2.99-7.36Z" />
          <path fill="#34A853" d="M12 22c2.7 0 4.96-.9 6.61-2.41l-3.22-2.51c-.9.6-2.05.97-3.39.97-2.6 0-4.81-1.76-5.6-4.12H3.08v2.59A9.99 9.99 0 0 0 12 22Z" />
          <path fill="#FBBC05" d="M6.4 13.93a6 6 0 0 1 0-3.86V7.48H3.08a10 10 0 0 0 0 9.04l3.32-2.59Z" />
          <path fill="#EA4335" d="M12 5.95c1.47 0 2.79.51 3.83 1.51l2.87-2.87A9.64 9.64 0 0 0 12 2a9.99 9.99 0 0 0-8.92 5.48l3.32 2.59C7.19 7.71 9.4 5.95 12 5.95Z" />
        </svg>
        {busy ? "Redirecting to Google…" : mode === "link" ? "Connect Google account" : "Continue with Google"}
      </button>
      <p id="google-availability" className="mt-2 text-xs leading-5 text-slate-400">
        {available === null
          ? "Checking Google sign-in…"
          : available === false
            ? "Google sign-in is currently unavailable on this deployment."
            : mode === "link"
              ? "Choose your Google account to connect it to this signed-in account."
              : "You will continue on Google's secure sign-in page."}
      </p>
      {error && <p role="alert" className="mt-3 text-sm text-red-300">{error}</p>}
    </div>
  );
}
