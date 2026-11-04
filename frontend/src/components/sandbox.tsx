"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

type Execution = {
  id: string;
  status: string;
  policy_decision: string;
  request_hash: string;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  duration: number | null;
  error_category?: string;
  approval_request?: { code: string };
  limits?: Record<string, number>;
};
async function api(path: string, body?: unknown) {
  const headers: Record<string, string> = {};
  if (body) {
    const c = await fetch("/api/auth/csrf", { cache: "no-store" });
    if (!c.ok) throw new Error("Authentication required");
    headers["X-CSRF-Token"] = (await c.json()).csrf_token;
    headers["Content-Type"] = "application/json";
  }
  const r = await fetch(`/api/sandbox${path}`, {
    method: body ? "POST" : "GET",
    headers,
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
    signal: AbortSignal.timeout(90000),
  });
  const data = await r.json();
  if (!r.ok)
    throw new Error(
      typeof data.detail === "string" ? data.detail : "Sandbox request failed",
    );
  return data;
}
export default function Sandbox() {
  const [code, setCode] = useState('print("Hello from the sandbox")');
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<Execution[]>([]);
  const [selected, setSelected] = useState<Execution | null>(null);
  const [more, setMore] = useState(false);
  async function load(offset = 0) {
    const d = await api(`/executions?offset=${offset}&limit=20`);
    setHistory((old) => (offset ? [...old, ...d.executions] : d.executions));
    setMore(d.executions.length === 20);
  }
  useEffect(() => {
    let live = true;
    Promise.all([api("/readiness"), api("/executions")])
      .then(([r, h]) => {
        if (live) {
          setReady(r.ready);
          setHistory(h.executions);
          setMore(h.executions.length === 20);
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, []);
  async function perform(action: () => Promise<Execution>) {
    setBusy(true);
    setError("");
    try {
      const result = await action();
      setSelected(await api(`/executions/${result.id}`));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sandbox request failed");
    } finally {
      setBusy(false);
    }
  }
  const bytes = new TextEncoder().encode(code).length;
  return (
    <main className="mx-auto max-w-5xl px-5 py-8">
      <Link href="/" className="text-sm text-teal-300">
        ← Dashboard
      </Link>
      <h1 className="mt-5 text-3xl font-semibold">Python Sandbox</h1>
      <p className="mt-3 text-sm text-slate-400">
        Isolated Python execution with deterministic policy and explicit
        approvals. Never enter secrets.
      </p>
      <p
        role="status"
        className="mt-5 rounded-lg border border-slate-700 p-4 text-sm"
      >
        {busy
          ? "Processing…"
          : ready
            ? "Sandbox readiness checks passed"
            : "SANDBOX_UNAVAILABLE · Execution is disabled until effective isolation checks pass."}
      </p>
      {error && (
        <p role="alert" className="mt-4 text-red-300">
          {error}
        </p>
      )}
      <div className="mt-6 grid gap-6 md:grid-cols-[1fr_220px]">
        <section className="min-w-0">
          <label htmlFor="python" className="text-sm">
            Python code
          </label>
          <textarea
            id="python"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            disabled={busy}
            rows={10}
            spellCheck={false}
            className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 p-4 font-mono text-sm"
          />
          <p className="mt-2 text-xs text-slate-400">
            {bytes}/32768 bytes · 128 MiB · 1 CPU · 32 PIDs · 10 seconds by
            default
          </p>
          <button
            disabled={busy || !ready || bytes > 32768 || !code.trim()}
            onClick={() => perform(() => api("/execute", { code }))}
            className="mt-4 rounded-lg bg-teal-300 px-5 py-3 font-semibold text-slate-950 disabled:opacity-40"
          >
            Execute Python
          </button>
          {selected && (
            <article className="mt-6 space-y-4 rounded-xl border border-slate-800 p-5">
              <h2 className="text-lg">Execution {selected.id.slice(0, 8)}</h2>
              <p>
                Status: {selected.status} · Policy: {selected.policy_decision}
              </p>
              {selected.error_category && (
                <p role="alert">{selected.error_category}</p>
              )}
              <p className="text-sm">
                Exit code: {selected.exit_code ?? "—"} · Duration:{" "}
                {selected.duration ?? "—"} seconds
              </p>
              {selected.approval_request &&
                selected.status === "pending_approval" && (
                  <section className="rounded border border-amber-700 p-4">
                    <h3 className="font-semibold">
                      Review exact execution request
                    </h3>
                    <pre className="mt-3 overflow-auto whitespace-pre-wrap break-words text-xs">
                      {selected.approval_request.code}
                    </pre>
                    <p className="mt-3 break-all text-xs text-slate-400">
                      Request hash: {selected.request_hash}
                    </p>
                    <pre className="mt-3 text-xs">
                      {JSON.stringify(selected.limits, null, 2)}
                    </pre>
                    <button
                      disabled={busy || !ready}
                      onClick={() =>
                        perform(() =>
                          api(`/approvals/${selected.id}`, {
                            approve: true,
                            request_hash: selected.request_hash,
                          }),
                        )
                      }
                      className="mt-4 rounded border border-amber-400 px-4 py-2 text-sm"
                    >
                      Approve exact request once
                    </button>
                  </section>
                )}
              <h3>stdout</h3>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words bg-slate-950 p-3 text-xs">
                {selected.stdout || "(empty)"}
              </pre>
              <h3>stderr</h3>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words bg-slate-950 p-3 text-xs">
                {selected.stderr || "(empty)"}
              </pre>
            </article>
          )}
        </section>
        <aside className="rounded-xl border border-slate-800 p-4">
          <h2 className="text-sm">Execution history</h2>
          <div className="mt-4 space-y-3">
            {history.map((e) => (
              <button
                key={e.id}
                disabled={busy}
                onClick={() => perform(() => api(`/executions/${e.id}`))}
                className="block w-full rounded border border-slate-700 p-3 text-left text-xs"
              >
                {e.id.slice(0, 8)} · {e.status}
              </button>
            ))}
          </div>
          {more && (
            <button
              disabled={busy}
              onClick={() =>
                load(history.length).catch((e) => setError(e.message))
              }
              className="mt-4 text-sm text-teal-300"
            >
              Load more
            </button>
          )}
        </aside>
      </div>
    </main>
  );
}
