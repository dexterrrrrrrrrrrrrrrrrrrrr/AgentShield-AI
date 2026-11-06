"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import WorkspaceNav from "./workspace-nav";
import { useSession } from "./session";
import { sessionExpired } from "@/lib/protected-api";
import { useCallback, useEffect, useRef, useState } from "react";
import { languageName } from "@/lib/languages";
import { monitoringApi } from "@/lib/monitor-client";

type Event = {
  id: string;
  seq: number;
  kind: string;
  timestamp: string;
  agent_id: string | null;
  execution_id: string | null;
  severity: string;
  category: string;
  tool: string | null;
  policy_decision: string | null;
  execution_result: string | null;
  duration: number | null;
  integrity?: "verified" | "legacy_unverified";
};
type Summary = {
  agent_executions: { total: number; successful: number; failed: number };
  sandbox_executions: { total: number; by_status: Record<string, number> };
  approvals: Record<string, number>;
  blocked_tool_requests: number;
  active_agents: {
    id: string;
    provider: string;
    model: string;
    updated_at: string;
    started_at?: string;
  }[];
  scope: string;
  websocket_origin_allowed?: boolean | null;
};
type Pending = { id: string; request_hash: string; expires_at: string };
type History = {
  id: string;
  agent_id: string | null;
  decision: string;
  timestamp: string;
  status: string;
};
type Review = {
  id: string;
  request_hash: string;
  agent_session_id: string | null;
  limits: Record<string, number>;
  status: string;
  approval_request?: { code: string; language?: string; stdin?: string };
};

export default function Monitoring() {
  const { active, user } = useSession();
  const search = useSearchParams();
  const [originAllowed, setOriginAllowed] = useState(true);
  const [reconnect, setReconnect] = useState(0);
  const [eventOffset, setEventOffset] = useState(50);
  const [olderEvents, setOlderEvents] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);
  const [history, setHistory] = useState<History[]>([]);
  const [review, setReview] = useState<Review | null>(null);
  const [connection, setConnection] = useState("Connecting…");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [clock, setClock] = useState(0);
  const [more, setMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const cursor = useRef(0);
  const hasPending = useRef(false);
  const refresh = useCallback(async () => {
    try {
      const [s, e, a] = await Promise.all([
        monitoringApi(
          `/monitor/summary?frontend_origin=${encodeURIComponent(window.location.origin)}`,
        ),
        monitoringApi("/monitor/events?limit=50"),
        monitoringApi("/monitor/approvals"),
      ]);
      setSummary(s);
      setOriginAllowed(s.websocket_origin_allowed !== false);
      setOlderEvents(e.events.length === 50);
      setEventOffset(50);
      setEvents((old) =>
        [
          ...new Map(
            [...old, ...e.events].map((v: Event) => [v.id, v]),
          ).values(),
        ]
          .sort((a, b) => b.seq - a.seq)
          .slice(0, 200),
      );
      setPending(a.pending);
      hasPending.current = a.pending.length > 0;
      setHistory(a.history);
      setOffset(0);
      setMore(a.pending.length === 20 || a.history.length === 20);
      setClock(Date.now());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Monitoring unavailable");
    }
  }, []);
  useEffect(() => {
    if (!active || !originAllowed) return;
    let live = true;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    let watchdog: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let connectedOnce = false;
    function scheduleRefresh() {
      if (!refreshTimer)
        refreshTimer = setTimeout(() => {
          refreshTimer = undefined;
          if (live) void refresh();
        }, 5000);
    }
    function scheduleReconnect() {
      if (!live) return;
      if (attempts >= 8) {
        setConnection("Disconnected · Reconnect when the service is available");
        return;
      }
      setConnection("Reconnecting…");
      retry = setTimeout(
        async () => {
          // Browsers report failed upgrade authentication as1006. Check the cookie
          // over REST before opening another socket rather than guessing its cause.
          try {
            const auth = await fetch("/api/auth/me", {
              cache: "no-store",
              credentials: "same-origin",
              signal: AbortSignal.timeout(5000),
            });
            if (!live) return;
            if (auth.status === 401) {
              live = false;
              sessionExpired();
              return;
            }
            if (!auth.ok) throw new Error("Authentication service unavailable");
            const current = await auth.json();
            if (current.id !== user.id) {
              live = false;
              window.location.replace("/");
              return;
            }
            connect();
          } catch {
            if (live) scheduleReconnect();
          }
        },
        Math.min(30000, 500 * 2 ** Math.min(attempts++, 6)) +
          Math.random() * 250,
      );
    }
    function connect() {
      if (!live) return;
      const url = new URL("/api/monitor/ws", window.location.href);
      url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      url.searchParams.set("after", String(cursor.current));
      const ws = new WebSocket(url);
      socket = ws;
      const opened = Date.now();
      function armWatchdog() {
        clearTimeout(watchdog);
        watchdog = setTimeout(() => {
          if (!live || socket !== ws) return;
          setConnection("Reconnecting…");
          // Browser application close codes must be1000 or3000–4999.
          ws.close(4000, "Monitoring heartbeat timeout");
        }, 45000);
      }
      armWatchdog();
      ws.onmessage = (message) => {
        if (!live || socket !== ws) return;
        try {
          const data = JSON.parse(message.data);
          if (
            ["connected", "heartbeat", "event", "resync_required"].includes(
              data.type,
            )
          )
            armWatchdog();
          if (data.type === "connected") {
            if (data.protocol !== 1)
              throw new Error("Unsupported monitoring protocol");
            setConnection("Live");
            if (connectedOnce) void refresh();
            connectedOnce = true;
          }
          if (data.type === "heartbeat") {
            if (ws.readyState === WebSocket.OPEN)
              ws.send(JSON.stringify({ type: "pong" }));
            setClock(Date.now());
            if (hasPending.current) scheduleRefresh();
          }
          if (data.type === "resync_required") {
            cursor.current = 0;
            setEvents([]);
            void refresh();
          }
          if (
            data.type === "event" &&
            Number.isSafeInteger(data.event?.seq) &&
            data.event.seq > cursor.current
          ) {
            cursor.current = data.event.seq;
            setEvents((old) =>
              [data.event, ...old.filter((e) => e.id !== data.event.id)]
                .sort((a, b) => b.seq - a.seq)
                .slice(0, 200),
            );
            scheduleRefresh();
          }
        } catch {
          setError("Invalid monitoring message; reconnecting");
          ws.close();
        }
      };
      ws.onclose = (event) => {
        if (!live || socket !== ws) return;
        socket = null;
        clearTimeout(watchdog);
        if (event.code === 4401) {
          live = false;
          sessionExpired();
          return;
        }
        if (event.code === 4403 || event.code === 1008) {
          setConnection("Monitoring authorization denied");
          return;
        }
        if (Date.now() - opened > 30000) attempts = 0;
        scheduleReconnect();
      };
      ws.onerror = () => {
        if (live) setConnection("Reconnecting…");
      };
    }
    const initial = setTimeout(() => {
      void refresh();
    }, 0);
    connect();
    return () => {
      live = false;
      clearTimeout(initial);
      clearTimeout(retry);
      clearTimeout(refreshTimer);
      clearTimeout(watchdog);
      socket?.close();
    };
  }, [refresh, active, user.id, originAllowed, reconnect]);
  const open = useCallback(async (id: string) => {
    setBusy(true);
    setError("");
    try {
      setReview(await monitoringApi(`/sandbox/executions/${id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to review");
    } finally {
      setBusy(false);
    }
  }, []);
  const requestedExecution = search.get("execution");
  useEffect(() => {
    const initial = setTimeout(() => {
      if (requestedExecution && /^[a-f0-9]{32}$/.test(requestedExecution))
        void open(requestedExecution);
      else setReview(null);
    }, 0);
    return () => clearTimeout(initial);
  }, [requestedExecution, open]);
  async function decide(reject: boolean) {
    if (!review) return;
    setBusy(true);
    setError("");
    try {
      await monitoringApi(
        `/sandbox/approvals/${review.id}${reject ? "/reject" : ""}`,
        reject
          ? { reject: true, request_hash: review.request_hash }
          : { approve: true, request_hash: review.request_hash },
      );
      setReview(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Decision failed");
    } finally {
      setBusy(false);
    }
  }
  async function older() {
    if (loadingOlder) return;
    setLoadingOlder(true);
    try {
      const next = offset + 20;
      const a = await monitoringApi(`/monitor/approvals?offset=${next}`);
      setPending((old) =>
        [
          ...new Map(
            [...old, ...a.pending].map((p: Pending) => [p.id, p]),
          ).values(),
        ].slice(0, 200),
      );
      setHistory((old) =>
        [
          ...new Map(
            [...old, ...a.history].map((h: History) => [h.id, h]),
          ).values(),
        ].slice(0, 200),
      );
      setOffset(next);
      setMore(a.pending.length === 20 || a.history.length === 20);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load history");
    } finally {
      setLoadingOlder(false);
    }
  }
  async function loadEvents() {
    if (loadingOlder) return;
    setLoadingOlder(true);
    try {
      const data = await monitoringApi(
        `/monitor/events?offset=${eventOffset}&limit=50`,
      );
      setEvents((old) =>
        [
          ...new Map(
            [...old, ...data.events].map((e: Event) => [e.id, e]),
          ).values(),
        ]
          .sort((a, b) => b.seq - a.seq)
          .slice(0, 200),
      );
      setEventOffset((n) => n + 50);
      setOlderEvents(data.events.length === 50 && eventOffset < 150);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load audit history");
    } finally {
      setLoadingOlder(false);
    }
  }
  const cards = summary
    ? [
        ["Total agent executions", summary.agent_executions.total],
        ["Successful", summary.agent_executions.successful],
        ["Failed", summary.agent_executions.failed],
        ["Blocked tool requests", summary.blocked_tool_requests],
        ["Pending approvals", summary.approvals.pending || 0],
        ["Sandbox executions", summary.sandbox_executions.total],
      ]
    : [];
  return (
    <main className="mx-auto max-w-7xl px-5 py-8">
      <WorkspaceNav />
      <header className="mt-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-xs tracking-widest text-teal-300">
            AGENTSHIELD AI · SECURITY OPERATIONS
          </p>
          <h1 className="mt-2 text-3xl font-semibold">Live Monitoring</h1>
          <p className="mt-2 text-sm text-slate-400">
            Execution activity, security decisions, and approvals for your
            workspace.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          {active && connection !== "Live" && (
            <button
              onClick={() => {
                void refresh();
                setConnection("Connecting…");
                setReconnect((n) => n + 1);
              }}
              className="rounded border border-slate-700 px-4 py-2 text-sm"
            >
              Reconnect monitoring
            </button>
          )}
          <p role="status" className="text-sm text-teal-300">
            {!active
              ? "Session ended"
              : !originAllowed
                ? "Monitoring authorization denied"
                : connection}
          </p>
          <button
            onClick={() => void refresh()}
            className="rounded border border-slate-700 px-4 py-2 text-sm"
          >
            Refresh
          </button>
        </div>
      </header>
      {error && (
        <p role="alert" className="mt-5 text-sm text-red-300">
          {error}
        </p>
      )}
      {!summary && (
        <div
          aria-busy="true"
          aria-label="Loading monitoring data"
          className="mt-6 h-20 rounded-xl bg-slate-900"
        />
      )}
      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-6">
        {cards.map(([label, value]) => (
          <section
            key={label}
            className="rounded-xl border border-slate-800 bg-[#0d1422] p-4"
          >
            <h2 className="text-xs text-slate-400">{label}</h2>
            <p className="mt-3 text-2xl font-semibold">{value}</p>
          </section>
        ))}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        {summary?.scope || "Loading stored analytics…"}
      </p>
      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-800 p-5">
          <h2 className="text-lg font-medium">Active agents</h2>
          {summary?.active_agents.length ? (
            summary.active_agents.map((a) => (
              <div key={a.id} className="mt-3 rounded bg-slate-900 p-3 text-sm">
                <Link
                  className="text-teal-300"
                  href={`/playground?session=${a.id}`}
                >
                  {a.id.slice(0, 8)}
                </Link>{" "}
                · {a.provider} · Running{" "}
                {a.started_at
                  ? `· ${Math.max(0, Math.round((clock - new Date(a.started_at).getTime()) / 1000))}s`
                  : ""}
              </div>
            ))
          ) : (
            <p className="mt-4 text-sm text-slate-400">No active agents.</p>
          )}
          <h3 className="mt-6 font-medium">Execution statistics</h3>
          {!summary ? (
            <p className="mt-3 text-sm text-slate-400">
              Loading execution statistics…
            </p>
          ) : (
            <>
              <p className="mt-3 text-sm text-slate-400">
                Approvals: {summary?.approvals.approved || 0} approved ·{" "}
                {summary?.approvals.rejected || 0} rejected ·{" "}
                {summary?.approvals.expired || 0} expired
              </p>
              <p className="mt-2 text-sm text-slate-400">
                Sandbox:{" "}
                {Object.entries(summary?.sandbox_executions.by_status || {})
                  .map(
                    ([status, count]) =>
                      `${count} ${status.replaceAll("_", " ")}`,
                  )
                  .join(" · ") || "No stored requests"}
              </p>
            </>
          )}
        </section>
        <section className="rounded-xl border border-slate-800 p-5">
          <h2 className="text-lg font-medium">Pending approvals</h2>
          {pending.filter((p) => new Date(p.expires_at).getTime() > clock)
            .length ? (
            pending
              .filter((p) => new Date(p.expires_at).getTime() > clock)
              .map((p) => (
                <div
                  key={p.id}
                  className="mt-3 flex items-center justify-between gap-3 rounded bg-slate-900 p-3 text-sm"
                >
                  <span>
                    {p.id.slice(0, 8)} · Expires{" "}
                    {new Date(p.expires_at).toISOString().slice(11, 19)} UTC
                  </span>
                  <button
                    disabled={busy}
                    onClick={() => open(p.id)}
                    className="text-teal-300"
                  >
                    Review request
                  </button>
                </div>
              ))
          ) : (
            <p className="mt-4 text-sm text-slate-400">No pending approvals.</p>
          )}
          <h3 className="mt-6 font-medium">Approval history</h3>
          <ul
            aria-label="Approval history"
            className="mt-3 max-h-48 space-y-2 overflow-auto text-sm text-slate-400"
          >
            {history.map((h) => (
              <li key={h.id}>
                {h.id.slice(0, 8)} · {h.decision} · {h.status}
                <time className="ml-2 text-xs">
                  {new Date(h.timestamp).toISOString().slice(0, 19)} UTC
                </time>
              </li>
            ))}
          </ul>
          {more && (
            <button
              disabled={loadingOlder}
              onClick={() => void older()}
              className="mt-3 text-sm text-teal-300"
            >
              Load more approvals
            </button>
          )}
        </section>
      </div>
      {review && (
        <section
          aria-label="Approval review"
          className="mt-6 rounded-xl border border-amber-800 p-5"
        >
          <h2 className="text-lg">Review exact request</h2>
          {review.agent_session_id && (
            <Link
              className="mt-3 block text-sm text-teal-300"
              href={`/playground?session=${review.agent_session_id}`}
            >
              Return to agent conversation after deciding
            </Link>
          )}
          <p className="mt-2 text-sm text-slate-400">
            Agent: {review.agent_session_id || "Manual execution"} · Execution:{" "}
            {review.id}
          </p>
          {review.approval_request && <p className="mt-3 text-sm">Language: {languageName(review.approval_request.language)}</p>}
          <pre className="mt-4 max-h-64 overflow-auto whitespace-pre-wrap break-words bg-slate-950 p-4 text-xs">
            {review.approval_request?.code ||
              "This approval is no longer pending."}
          </pre>
          {review.approval_request && <><h3 className="mt-3 text-sm">Standard input</h3><pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words text-xs">{review.approval_request.stdin || "(empty)"}</pre></>}
          <p className="mt-3 break-all text-xs text-slate-500">
            Request hash: {review.request_hash}
          </p>
          <pre className="mt-3 text-xs text-slate-400">
            {JSON.stringify(review.limits, null, 2)}
          </pre>
          {review.approval_request && (
            <div className="mt-4 flex gap-3">
              <button
                disabled={busy}
                onClick={() => decide(false)}
                className="rounded bg-teal-300 px-4 py-2 text-sm font-semibold text-slate-950"
              >
                Approve exact request
              </button>
              <button
                disabled={busy}
                onClick={() => decide(true)}
                className="rounded border border-red-600 px-4 py-2 text-sm text-red-300"
              >
                Reject request
              </button>
            </div>
          )}
          <button
            onClick={() => setReview(null)}
            className="mt-4 text-xs text-slate-400"
          >
            Close review
          </button>
        </section>
      )}
      <section className="mt-6 rounded-xl border border-slate-800 p-5">
        <h2 className="text-lg font-medium">Recent activity timeline</h2>
        <p className="mt-2 text-xs text-slate-500">
          Status events only. No prompts, tool payloads, code, or private
          reasoning.
        </p>
        <ol
          aria-label="Activity timeline"
          className="mt-4 max-h-[32rem] space-y-2 overflow-auto"
        >
          {events.map((e) => (
            <li
              key={e.id}
              className="rounded-lg bg-slate-900 px-4 py-3 text-sm"
            >
              <div className="flex flex-wrap justify-between gap-2">
                <span
                  className={
                    e.severity === "warning"
                      ? "text-amber-300"
                      : "text-teal-300"
                  }
                >
                  {e.kind.replaceAll("_", " ")}
                </span>
                <time className="text-xs text-slate-500">
                  #{e.seq} · {new Date(e.timestamp).toISOString().slice(11, 19)}{" "}
                  UTC
                </time>
              </div>
              <p className="mt-2 break-words text-xs text-slate-400">
                {e.agent_id ? `Agent ${e.agent_id.slice(0, 8)} · ` : ""}
                {e.tool ? `${e.tool} · ` : ""}
                {e.policy_decision ? `${e.policy_decision} · ` : ""}
                {e.execution_result || "Status update"}
                {e.duration !== null ? ` · ${e.duration}s` : ""}
                {e.integrity === "legacy_unverified"
                  ? " · Legacy audit (unsigned)"
                  : ""}
              </p>
            </li>
          ))}
        </ol>
        {!events.length && (
          <p className="py-6 text-sm text-slate-400">
            No stored activity yet. Run a task in the Playground.
          </p>
        )}
        {olderEvents && events.length < 200 && (
          <button
            disabled={loadingOlder}
            onClick={() => void loadEvents()}
            className="mt-4 text-sm text-teal-300"
          >
            {loadingOlder
              ? "Loading audit history…"
              : "Load older audit events"}
          </button>
        )}
        <h3 className="mt-6 font-medium">Tool execution history</h3>
        <ul className="mt-3 space-y-2 text-sm text-slate-400">
          {events
            .filter((e) => e.tool)
            .slice(0, 20)
            .map((e) => (
              <li key={e.id}>
                {e.tool} · {e.kind.replaceAll("_", " ")} ·{" "}
                {e.execution_result || e.policy_decision || "requested"}
              </li>
            ))}
        </ul>
        <h3 className="mt-6 font-medium">Security events</h3>
        <ul className="mt-3 space-y-2 text-sm text-slate-400">
          {events
            .filter((e) => e.category === "security")
            .slice(0, 10)
            .map((e) => (
              <li key={e.id}>
                {e.kind.replaceAll("_", " ")} · {e.severity} ·{" "}
                {e.policy_decision || e.execution_result}
              </li>
            ))}
        </ul>
      </section>
    </main>
  );
}
