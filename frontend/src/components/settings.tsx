"use client";
import Link from "next/link";
import { StatusBadge } from "./ui";
import { useEffect, useState } from "react";
import { agentApi } from "@/lib/agent-client";
import { monitoringApi } from "@/lib/monitor-client";

type Metadata = {
  providers: {
    id: string;
    model: string;
    configured: boolean;
    enabled: boolean;
  }[];
  tools: string[];
};
export default function Settings() {
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [sandbox, setSandbox] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    agentApi("/providers")
      .then((data) => {
        if (live) {
          setMetadata(data);
          setError("");
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [attempt]);
  async function checkSandbox() {
    setBusy(true);
    setError("");
    try {
      const data = await monitoringApi("/sandbox/readiness");
      setSandbox(data.ready);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Readiness check unavailable");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="mx-auto max-w-5xl px-5 py-8">
      <p className="text-xs tracking-widest text-teal-300">
        WORKSPACE CONFIGURATION
      </p>
      <h1 className="mt-3 text-3xl font-semibold">Workspace settings</h1>
      <p className="mt-3 text-sm leading-6 text-slate-400">
        Provider and security settings are controlled by your deployment. API
        keys remain on the backend. Configure the provider, model, and tool
        permissions for each new agent conversation in the Playground.
      </p>
      {error && (
        <p role="alert" className="mt-5 text-red-300">
          {error}
        </p>
      )}
      {!metadata && (
        <div
          aria-busy="true"
          aria-label="Loading provider settings"
          className="mt-6 h-32 rounded-xl bg-slate-900"
        />
      )}
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {metadata?.providers.map((p) => (
          <section
            key={p.id}
            className="rounded-xl border border-slate-800 bg-[#0d1422] p-5"
          >
            <div className="section-heading"><h2 className="text-lg font-semibold capitalize">{p.id}</h2><StatusBadge tone={p.enabled && p.configured ? "info" : "warning"}>{p.enabled && p.configured ? "Configured" : "Setup required"}</StatusBadge></div>
            <p className="mt-3 break-words font-mono text-sm text-slate-300">
              {p.model}
            </p>
            <p
              className={`mt-3 text-sm ${p.enabled && p.configured ? "text-teal-300" : "text-amber-200"}`}
            >
              {!p.enabled
                ? "Disabled by the server"
                : p.configured
                  ? "Configured on the server"
                  : "Not configured — backend setup required"}
            </p>
            <p className="mt-3 text-xs leading-5 text-slate-500">
              {p.id === "groq"
                ? "Optional hosted provider. Free-tier quotas apply; no automatic paid fallback."
                : "Optional local inference. A lightweight installed model is recommended for an 8 GB Mac; no models are downloaded automatically."}
            </p>
          </section>
        ))}
      </div>
      <section className="mt-6 rounded-xl border border-slate-800 p-5">
        <h2 className="text-lg font-medium">Agent configuration</h2>
        <p className="mt-3 text-sm text-slate-400">
          Server-supported tools: {metadata?.tools.join(", ") || "Loading…"}.
          Choose a subset when creating a conversation. Saved conversations
          retain their original configuration.
        </p>
        <Link
          href="/playground"
          className="mt-4 inline-block text-sm text-teal-300"
        >
          Configure a new conversation →
        </Link>
      </section>
      <section className="mt-6 rounded-xl border border-slate-800 p-5">
        <h2 className="text-lg font-medium">Sandbox safety</h2>
        <p className="mt-3 text-sm text-slate-400">
          Code execution requires independent policy checks and verified
          isolation. This page cannot enable execution or change resource
          limits.
        </p>
        <p className="mt-3 text-sm text-amber-200">
          {sandbox === null
            ? "Readiness has not been checked in this view."
            : sandbox
              ? "Sandbox readiness checks passed for this deployment."
              : "SANDBOX_UNAVAILABLE · No code will execute."}
        </p>
        <button
          disabled={busy}
          onClick={() => void checkSandbox()}
          className="mt-4 rounded border border-slate-700 px-4 py-2 text-sm"
        >
          {busy ? "Checking isolation…" : "Check sandbox readiness"}
        </button>
      </section>
      <button
        onClick={() => setAttempt((n) => n + 1)}
        className="mt-6 text-sm text-teal-300"
      >
        Refresh provider settings
      </button>
    </main>
  );
}
