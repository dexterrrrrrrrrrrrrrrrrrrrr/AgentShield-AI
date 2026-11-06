"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { monitoringApi } from "@/lib/monitor-client";
import { agentApi } from "@/lib/agent-client";
import { PageHeader, MetricCard, StatusBadge, Icon } from "./ui";
type Connection = "checking" | "connected" | "unavailable";
export default function Dashboard() {
  const [overview, setOverview] = useState<{
    agent_executions: { total: number; successful: number };
    sandbox_executions: { total: number };
    active_agents: unknown[];
    approvals: { pending: number };
    blocked_tool_requests: number;
  } | null>(null);
  const [events, setEvents] = useState<{id: string; kind: string; timestamp: string; execution_result?: string}[]>([]);
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
    Promise.all([monitoringApi("/monitor/summary"), agentApi("/providers"), monitoringApi("/monitor/events?limit=6")])
      .then(([summary, metadata, activity]) => {
        if (live) {
          setOverview(summary);
          setEvents(activity.events);
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

  return <main className="console-page">
    <PageHeader eyebrow="OPERATIONS / OVERVIEW" title="Dashboard overview" description="Your command center for safer agent development.">
      <Link href="/playground" className="button-primary">Open Playground <Icon name="arrow" /></Link>
    </PageHeader>
    <section aria-label="Backend connectivity" className="health-strip">
      <div><span className="eyebrow">SYSTEM CONNECTION</span><p role="status" className="mt-2 text-sm">{connection === "connected" ? "Connected · FastAPI is healthy" : connection === "checking" ? "Checking API health…" : "API unavailable · Check the backend and API URL"}</p></div>
      <button onClick={retry} disabled={connection === "checking"} className="button-secondary">Refresh status</button>
    </section>
    {overviewError && <p role="alert">{overviewError}</p>}
    {!overview && !overviewError && <div aria-busy="true" aria-label="Loading workspace metrics" className="skeleton" />}
    <div className="metrics-grid">{[
      ["Agent executions", overview?.agent_executions.total, "Stored agent turns"],
      ["Active agents", overview?.active_agents.length, "Running conversations"],
      ["Sandbox executions", overview?.sandbox_executions.total, "Stored execution requests"],
      ["Successful agent runs", overview?.agent_executions.successful, "Completed agent turns"],
      ["Pending approvals", overview?.approvals.pending, "Awaiting your decision"],
      ["Blocked tool requests", overview?.blocked_tool_requests, "Retained security events"],
    ].map(([label, value, note]) => <MetricCard key={String(label)} label={String(label)} value={value ?? "—"} note={String(note)} />)}</div>
    <div className="dashboard-grid">
      <section className="console-card"><div className="section-heading"><h2>Recent activity</h2><Link href="/monitoring">View monitoring <span className="inline-block align-middle"><Icon name="arrow" /></span></Link></div>
        <p className="text-sm text-slate-400">Your retained execution and policy events.</p>
        <ol className="activity-list">{events.map(event => <li key={event.id}><span className="activity-marker" /><div><p>{event.kind.replaceAll("_", " ")}</p><span className="text-xs text-slate-400">{event.execution_result || "Status update"}</span></div><time>{new Date(event.timestamp).toISOString().slice(11,19)} UTC</time></li>)}</ol>
        {!events.length && <div className="empty-state">{overviewError ? "Activity unavailable. Refresh to retry." : overview ? "No activity recorded. Your first execution will appear here." : "Loading activity…"}</div>}
      </section>
      <section className="console-card"><div className="section-heading"><h2>Execution workspace</h2><Icon name="shield" /></div><p className="text-sm text-slate-400">Purpose-built tools. Explicit boundaries.</p>
        <div className="action-list">{[["Playground", "/playground", "Conversations & scoped agent tools"], ["Sandbox", "/sandbox", "Six languages. Isolated execution."], ["Monitoring", "/monitoring", "Policy decisions & signed audit history"]].map(([name,href,note]) => <Link key={href} href={href}><Icon name={name} /><div><strong>{name}</strong><small>{note}</small></div><span><Icon name="arrow" /></span></Link>)}</div>
      </section>
    </div>
    <section className="provider-strip"><div><p className="eyebrow">AI PROVIDER</p><p className="mt-2 text-sm text-slate-400">{providerReady === null ? "Checking provider configuration…" : providerReady ? "An AI provider is configured. Open the Playground to run a task." : "Provider setup required. Open Settings to review Groq and optional Ollama configuration."}</p></div><StatusBadge tone={providerReady ? "info" : "warning"}>{providerReady === null ? "Checking" : providerReady ? "Configured · not a live check" : "Setup required"}</StatusBadge></section>
    <footer className="console-footer">AGENTSHIELD / AI <span>Scoped tools · Isolated execution · Signed audit trails</span></footer>
  </main>;
}
