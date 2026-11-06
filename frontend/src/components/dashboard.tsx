"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogoutButton, useUser } from "./session";
import { useCallback, useEffect, useState } from "react";
import { monitoringApi } from "@/lib/monitor-client";
import { agentApi } from "@/lib/agent-client";

const sections = [
  "Overview",
  "Agent Playground",
  "Sandbox",
  "Execution Logs",
  "Security Monitoring",
  "Settings",
] as const;
type Section = (typeof sections)[number];
const routes: Record<Section, string> = {
  Overview: "/",
  "Agent Playground": "/playground",
  Sandbox: "/sandbox",
  "Execution Logs": "/monitoring",
  "Security Monitoring": "/monitoring",
  Settings: "/settings",
};
type Connection = "checking" | "connected" | "unavailable";
const descriptions: Record<Section, string> = {
  Overview: "Your command center for safer agent development.",
  "Agent Playground": "Conversations with bounded, permission-checked tools.",
  Sandbox: "Isolated multi-language execution with independent security policies.",
  "Execution Logs": "Your stored execution history and live activity.",
  "Security Monitoring":
    "Policy decisions, signed audit events, and human approvals.",
  Settings: "Server provider status and per-conversation tool configuration.",
};

export default function Dashboard() {
  const user = useUser();
  const router = useRouter();
  const active: Section = "Overview";
  const [overview, setOverview] = useState<{
    agent_executions: { total: number };
    active_agents: unknown[];
    approvals: { pending: number };
    blocked_tool_requests: number;
  } | null>(null);
  const [providerReady, setProviderReady] = useState<boolean | null>(null);
  const [overviewError, setOverviewError] = useState("");
  const [connection, setConnection] = useState<Connection>("checking");
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    let disposed = false;
    async function check() {
      setConnection("checking");
      try {
        const base = process.env.NEXT_PUBLIC_API_URL || "/api";
        const response = await fetch(`${base.replace(/\/$/, "")}/health`, {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok) throw new Error("Health request failed");
        const data: unknown = await response.json();
        if (
          typeof data !== "object" ||
          data === null ||
          !("status" in data) ||
          data.status !== "ok"
        )
          throw new Error("Unexpected health response");
        if (!disposed) setConnection("connected");
      } catch {
        if (!disposed) setConnection("unavailable");
      } finally {
        clearTimeout(timeout);
      }
    }
    void check();

    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timeout);
    };
  }, [attempt]);

  useEffect(() => {
    let live = true;
    Promise.all([monitoringApi("/monitor/summary"), agentApi("/providers")])
      .then(([summary, metadata]) => {
        if (live) {
          setOverview(summary);
          setProviderReady(
            metadata.providers.some(
              (p: { enabled: boolean; configured: boolean }) =>
                p.enabled && p.configured,
            ),
          );
          setOverviewError("");
        }
      })
      .catch((e) => {
        if (live)
          setOverviewError(
            e instanceof Error ? e.message : "Unable to load workspace state",
          );
      });
    return () => {
      live = false;
    };
  }, [attempt]);

  return (
    <div className="min-h-screen lg:flex">
      <aside className="border-b border-slate-800 bg-[#0d1422] p-5 lg:fixed lg:inset-y-0 lg:w-64 lg:border-r lg:border-b-0">
        <Link
          href="/"
          className="flex items-center gap-3 text-lg font-bold tracking-tight"
        >
          <span
            aria-hidden="true"
            className="rounded-xl bg-teal-400/15 px-3 py-2 text-teal-300"
          >
            ◈
          </span>
          AgentShield <span className="text-teal-300">AI</span>
        </Link>
        <p className="mt-8 mb-3 text-xs font-semibold tracking-widest text-slate-500">
          WORKSPACE
        </p>
        <nav
          aria-label="Main navigation"
          className="flex flex-wrap gap-2 lg:flex-col"
        >
          {sections.map((section, index) => (
            <button
              key={section}
              onClick={() => router.push(routes[section])}
              aria-current={active === section ? "page" : undefined}
              className={`flex items-center gap-3 rounded-lg px-4 py-3 text-left text-sm transition-colors ${active === section ? "bg-teal-400/10 text-teal-300" : "text-slate-400 hover:bg-slate-800 hover:text-white"}`}
            >
              <span aria-hidden="true" className="w-5 text-center">
                {["▦", "◇", "⬡", "≡", "◎", "⚙"][index]}
              </span>
              {section}
            </button>
          ))}
        </nav>
        <div className="mt-8 rounded-xl border border-slate-800 p-4 lg:absolute lg:right-5 lg:bottom-6 lg:left-5">
          <p className="text-sm font-medium">Security workspace</p>
          <p className="mt-2 text-xs leading-5 text-slate-400">
            Policy-enforced local deployment
          </p>
        </div>
      </aside>
      <div className="min-w-0 flex-1 lg:ml-64">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-6 py-5 lg:px-10">
          <p className="text-sm text-slate-400">
            Workspace <span className="mx-2 text-slate-600">/</span>
            <span className="text-slate-200">{active}</span>
          </p>
          <div className="flex flex-wrap items-center gap-4">
            <Link
              href="/profile"
              className="text-sm text-teal-300 hover:underline"
            >
              {user.full_name} · Profile
            </Link>
            <LogoutButton />
            <span className="rounded-full border border-teal-800 bg-teal-950/50 px-3 py-1 text-xs text-teal-300">
              Local workspace
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-6 py-9 lg:px-10">
          <p className="mb-2 text-xs font-semibold tracking-[0.2em] text-teal-400">
            AGENTSHIELD WORKSPACE
          </p>
          <h1 className="text-3xl font-semibold tracking-tight">
            {active === "Overview" ? "Dashboard overview" : active}
          </h1>
          <p className="mt-3 text-sm leading-6 text-slate-400">
            {descriptions[active]}
          </p>
          <section
            aria-label="Backend connectivity"
            className="mt-7 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900/50 p-5"
          >
            <div>
              <h2 className="text-sm font-medium">Backend connection</h2>
              <p
                role="status"
                aria-live="polite"
                className={`mt-2 text-sm ${connection === "connected" ? "text-teal-300" : connection === "unavailable" ? "text-amber-300" : "text-slate-400"}`}
              >
                {connection === "connected"
                  ? "Connected · FastAPI is healthy"
                  : connection === "checking"
                    ? "Checking API health…"
                    : "API unavailable · Check the backend and API URL"}
              </p>
            </div>
            <button
              onClick={retry}
              disabled={connection === "checking"}
              className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:border-teal-400 disabled:cursor-wait disabled:opacity-40"
            >
              Refresh status
            </button>
          </section>
          {overviewError && (
            <p role="alert" className="mt-5 text-sm text-red-300">
              {overviewError}
            </p>
          )}
          {!overview && !overviewError && (
            <div
              aria-busy="true"
              aria-label="Loading workspace metrics"
              className="mt-6 h-12 rounded bg-slate-900"
            />
          )}
          <>
            <p className="mt-5 text-sm text-slate-400">
              {providerReady === null
                ? "Checking provider configuration…"
                : providerReady
                  ? "An AI provider is configured. Open the Playground to run a task."
                  : "Provider setup required. Open Settings to review Groq and optional Ollama configuration."}
            </p>
            <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {[
                [
                  "Agent executions",
                  overview?.agent_executions.total ?? "—",
                  "Current stored agent turns",
                ],
                [
                  "Active agents",
                  overview?.active_agents.length ?? "—",
                  "Running authenticated conversations",
                ],
                [
                  "Pending approvals",
                  overview?.approvals.pending ?? "—",
                  "Expiring requests requiring your decision",
                ],
                [
                  "Blocked tool requests",
                  overview?.blocked_tool_requests ?? "—",
                  "Retained security rejection events",
                ],
              ].map(([title, value, note]) => (
                <section
                  key={title}
                  className="rounded-xl border border-slate-800 bg-[#0e1726] p-5"
                >
                  <h2 className="text-sm text-slate-400">{title}</h2>
                  <p className="mt-4 text-xl font-semibold">{value}</p>
                  <p className="mt-3 text-xs text-slate-500">{note}</p>
                </section>
              ))}
            </div>
            <div className="mt-7 grid gap-6 xl:grid-cols-2">
              <section className="rounded-xl border border-slate-800 p-6">
                <h2 className="text-lg font-medium">Explore your workspace</h2>
                <p className="mt-2 text-sm text-slate-400">
                  Create conversations, review controlled executions, and
                  monitor your activity.
                </p>
                <div className="mt-5 space-y-3">
                  {sections.slice(1, 4).map((section) => (
                    <button
                      key={section}
                      onClick={() => router.push(routes[section])}
                      className="flex w-full items-center justify-between rounded-lg bg-slate-900 px-4 py-4 text-left text-sm hover:bg-slate-800"
                    >
                      <span>{section}</span>
                      <span aria-hidden="true" className="text-teal-300">
                        →
                      </span>
                    </button>
                  ))}
                </div>
              </section>
              <section className="rounded-xl border border-slate-800 p-6">
                <h2 className="text-lg font-medium">
                  Built with clear boundaries
                </h2>
                <p className="mt-4 text-sm leading-7 text-slate-400">
                  Run bounded text agents with permission-checked tools and
                  saved conversations. Sandbox execution requires verified
                  isolation and policy approval. Live monitoring shows your
                  execution activity, policy decisions, and approvals.
                </p>
                <div className="mt-6 rounded-lg border border-teal-900 bg-teal-950/30 p-4 text-sm leading-6 text-teal-200">
                  Agents can use only server-authorized tools. Code execution
                  requires sandbox readiness and policy checks.
                </div>
              </section>
            </div>
          </>
          <footer className="mt-10 text-xs text-slate-500">
            AgentShield AI · Security operations workspace
          </footer>
        </main>
      </div>
    </div>
  );
}
