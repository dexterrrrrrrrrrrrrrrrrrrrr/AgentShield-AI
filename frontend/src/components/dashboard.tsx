"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogoutButton, useUser } from "./session";
import { useCallback, useEffect, useState } from "react";

const sections = [
  "Overview",
  "Agent Playground",
  "Sandbox",
  "Execution Logs",
  "Security Monitoring",
  "Settings",
] as const;
type Section = (typeof sections)[number];
type Connection = "checking" | "connected" | "unavailable";
const descriptions: Record<Section, string> = {
  Overview: "Your command center for safer agent development.",
  "Agent Playground":
    "A future workspace for designing and evaluating AI agents.",
  Sandbox: "A future isolated environment for controlled agent execution.",
  "Execution Logs":
    "Agent execution history will appear here when execution is available.",
  "Security Monitoring":
    "Security events and policy insights will appear here in a future phase.",
  Settings: "Workspace configuration will be available in a future phase.",
};

export default function Dashboard() {
  const user = useUser();
  const router = useRouter();
  const [active, setActive] = useState<Section>("Overview");
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
              onClick={() =>
                [
                  "Agent Playground",
                  "Sandbox",
                  "Security Monitoring",
                  "Execution Logs",
                ].includes(section)
                  ? router.push(
                      section === "Sandbox"
                        ? "/sandbox"
                        : section === "Agent Playground"
                          ? "/playground"
                          : "/monitoring",
                    )
                  : setActive(section)
              }
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
          <p className="text-sm font-medium">Foundation release</p>
          <p className="mt-2 text-xs leading-5 text-slate-400">
            Phase 5 · Development workspace
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
              Phase 5
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
          {active === "Overview" ? (
            <>
              <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {[
                  [
                    "Agents",
                    "Playground ready",
                    "Configure a provider to start",
                  ],
                  [
                    "Sandbox",
                    "Policy-gated",
                    "Readiness required before execution",
                  ],
                  [
                    "Execution logs",
                    "Live monitoring",
                    "Open Execution Logs for your activity",
                  ],
                  [
                    "Security events",
                    "Policy events",
                    "Open Security Monitoring for stored records",
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
                  <h2 className="text-lg font-medium">
                    Explore your workspace
                  </h2>
                  <p className="mt-2 text-sm text-slate-400">
                    The foundation is in place. Explore what comes next.
                  </p>
                  <div className="mt-5 space-y-3">
                    {sections.slice(1, 4).map((section) => (
                      <button
                        key={section}
                        onClick={() =>
                          [
                            "Agent Playground",
                            "Sandbox",
                            "Execution Logs",
                            "Security Monitoring",
                          ].includes(section)
                            ? router.push(
                                section === "Sandbox"
                                  ? "/sandbox"
                                  : section === "Agent Playground"
                                    ? "/playground"
                                    : "/monitoring",
                              )
                            : setActive(section)
                        }
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
                    Agents can use only server-authorized tools. Python
                    execution requires sandbox readiness and policy checks.
                  </div>
                </section>
              </div>
            </>
          ) : (
            <section className="mt-6 rounded-xl border border-dashed border-slate-700 px-6 py-16 text-center">
              <span aria-hidden="true" className="text-4xl text-teal-400">
                ◇
              </span>
              <h2 className="mt-5 text-xl font-medium">
                {active} is coming in a future phase
              </h2>
              <p className="mx-auto mt-3 max-w-lg text-sm leading-6 text-slate-400">
                {descriptions[active]} This section is a placeholder in Phase 5.
              </p>
              <button
                onClick={() => setActive("Overview")}
                className="mt-6 rounded-lg bg-teal-300 px-5 py-3 text-sm font-semibold text-slate-950 hover:bg-teal-200"
              >
                Back to overview
              </button>
            </section>
          )}
          <footer className="mt-10 text-xs text-slate-500">
            AgentShield AI · Phase 5 foundation
          </footer>
        </main>
      </div>
    </div>
  );
}
