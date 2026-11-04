"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { authPost } from "@/lib/auth-client";

export default function AuthForm({ mode }: { mode: "login" | "register" }) {
  const registering = mode === "register";
  const router = useRouter();
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") || "");
    const confirm = String(form.get("confirm_password") || "");
    if (registering && password !== confirm) {
      setError("Passwords must match.");
      return;
    }
    if (registering && !password.trim()) {
      setError("Choose a password with at least 12 characters.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await authPost(mode, {
        email: String(form.get("email") || "").trim(),
        password,
        ...(registering
          ? {
              full_name: String(form.get("full_name") || "").trim(),
              confirm_password: confirm,
            }
          : {}),
      });
      router.replace(registering ? "/login?registered=1" : "/");
      router.refresh();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to connect. Please try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  const inputClass =
    "mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white focus:border-teal-300 focus:outline-none";
  return (
    <main className="flex min-h-screen items-center justify-center px-5 py-10">
      <section className="w-full max-w-md rounded-2xl border border-slate-800 bg-[#0d1422] p-7 shadow-xl sm:p-9">
        <Link href="/" className="text-lg font-bold tracking-tight">
          ◈ AgentShield <span className="text-teal-300">AI</span>
        </Link>
        <p className="mt-8 text-xs font-semibold tracking-widest text-teal-400">
          SECURE WORKSPACE
        </p>
        <h1 className="mt-3 text-2xl font-semibold">
          {registering ? "Create your account" : "Welcome back"}
        </h1>
        <p className="mt-2 text-sm leading-6 text-slate-400">
          {registering
            ? "Start with a secure foundation for your workspace."
            : "Sign in to your AgentShield AI workspace."}
        </p>
        <form onSubmit={submit} className="mt-7 space-y-5">
          <fieldset
            disabled={loading}
            className="space-y-5 disabled:opacity-70"
          >
            {registering && (
              <label className="block text-sm" htmlFor="full_name">
                Full name
                <input
                  id="full_name"
                  name="full_name"
                  autoComplete="name"
                  required
                  minLength={2}
                  maxLength={100}
                  className={inputClass}
                />
              </label>
            )}
            <label className="block text-sm" htmlFor="email">
              Email address
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                maxLength={254}
                className={inputClass}
              />
            </label>
            <label className="block text-sm" htmlFor="password">
              Password
              <input
                id="password"
                name="password"
                type={visible ? "text" : "password"}
                autoComplete={registering ? "new-password" : "current-password"}
                required
                minLength={registering ? 12 : 1}
                maxLength={128}
                aria-describedby={registering ? "password-help" : undefined}
                className={inputClass}
              />
            </label>
            {registering && (
              <>
                <p
                  id="password-help"
                  className="-mt-3 text-xs leading-5 text-slate-400"
                >
                  Use 12–128 characters. A long, unique passphrase is
                  recommended.
                </p>
                <label className="block text-sm" htmlFor="confirm_password">
                  Confirm password
                  <input
                    id="confirm_password"
                    name="confirm_password"
                    type={visible ? "text" : "password"}
                    autoComplete="new-password"
                    required
                    minLength={12}
                    maxLength={128}
                    className={inputClass}
                  />
                </label>
              </>
            )}
            <button
              type="button"
              onClick={() => setVisible(!visible)}
              aria-pressed={visible}
              className="text-xs text-teal-300 hover:underline"
            >
              {visible ? "Hide" : "Show"}{" "}
              {registering ? "passwords" : "password"}
            </button>
            {error && (
              <p
                role="alert"
                className="rounded-lg border border-red-900 bg-red-950/30 p-3 text-sm leading-6 text-red-200"
              >
                {error}
              </p>
            )}
            <button
              type="submit"
              className="w-full rounded-lg bg-teal-300 px-4 py-3 text-sm font-semibold text-slate-950 hover:bg-teal-200 disabled:cursor-wait"
              disabled={loading}
            >
              {loading
                ? "Please wait…"
                : registering
                  ? "Create account"
                  : "Sign in"}
            </button>
          </fieldset>
          <p role="status" aria-live="polite" className="sr-only">
            {loading ? "Submitting your request" : ""}
          </p>
        </form>
        <p className="mt-6 text-center text-sm text-slate-400">
          {registering ? "Already have an account?" : "New to AgentShield?"}{" "}
          <Link
            href={registering ? "/login" : "/register"}
            className="font-medium text-teal-300 hover:underline"
          >
            {registering ? "Sign in" : "Create an account"}
          </Link>
        </p>
      </section>
    </main>
  );
}
