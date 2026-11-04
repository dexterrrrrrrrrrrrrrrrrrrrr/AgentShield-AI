"use client";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { agentApi } from "@/lib/agent-client";

type Provider = {
  id: string;
  model: string;
  enabled: boolean;
  configured: boolean;
};
type Session = { id: string; provider: string; model: string; status: string };
type Event = { kind: string; tool?: string; input?: string; output?: string };
type Turn = {
  id: string;
  user_content: string;
  assistant_content: string;
  status: string;
  events: Event[];
};

export default function Playground() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [provider, setProvider] = useState("groq");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [last, setLast] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const current = providers.find((p) => p.id === provider);

  async function refresh(offset = 0) {
    const data = await agentApi(`/sessions?offset=${offset}&limit=20`);
    setSessions((old) => (offset ? [...old, ...data.sessions] : data.sessions));
    setHasMore(data.sessions.length === 20);
  }
  useEffect(() => {
    let live = true;
    Promise.all([agentApi("/providers"), agentApi("/sessions?limit=20")])
      .then(([p, s]) => {
        if (live) {
          setProviders(p.providers);
          setSessions(s.sessions);
          setHasMore(s.sessions.length === 20);
          setReady(true);
        }
      })
      .catch((e) => {
        if (live) {
          setError(e.message);
          setReady(true);
        }
      });
    return () => {
      live = false;
    };
  }, []);

  async function open(session: Session) {
    setBusy(true);
    setError("");
    try {
      const data = await agentApi(`/sessions/${session.id}/messages?limit=50`);
      setSelected(data.session);
      setProvider(data.session.provider);
      setMessages(data.messages);
      setLast("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load conversation");
    } finally {
      setBusy(false);
    }
  }
  async function send(content: string) {
    if (!content.trim() || !current) return;
    setBusy(true);
    setError("");
    setLast(content);
    try {
      const session =
        selected ||
        (await agentApi("/sessions", "POST", {
          provider,
          model: current.model,
          allowed_tools: ["calculator", "summarize_text", "format_json"],
        }));
      setSelected(session);
      const turn = await agentApi(`/sessions/${session.id}/messages`, "POST", {
        content,
      });
      setMessages((old) => [...old, turn].slice(-50));
      setText("");
      if (turn.status === "failed") setError(turn.assistant_content);
      else setLast("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to send message");
    } finally {
      setBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    await send(text);
  }
  async function clear() {
    if (!selected) {
      setMessages([]);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await agentApi(`/sessions/${selected.id}`, "DELETE");
      setSelected(null);
      setMessages([]);
      setLast("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to clear conversation");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="mx-auto max-w-6xl px-5 py-8">
      <Link href="/" className="text-sm text-teal-300">
        ← Dashboard
      </Link>
      <header className="my-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-xs tracking-widest text-teal-300">
            AGENTSHIELD AI · PHASE 3
          </p>
          <h1 className="mt-2 text-3xl font-semibold">Agent Playground</h1>
          <p className="mt-2 text-sm text-slate-400">
            Text-only agents with bounded, permission-checked tools.
          </p>
        </div>
        <p role="status" aria-live="polite" className="text-sm text-teal-300">
          {busy ? "Running…" : !ready ? "Loading…" : "Ready"}
        </p>
      </header>
      <div className="grid gap-5 md:grid-cols-[220px_1fr]">
        <aside
          aria-label="Conversations"
          className="rounded-xl border border-slate-800 bg-[#0d1422] p-4"
        >
          <button
            disabled={busy}
            onClick={() => {
              setSelected(null);
              setMessages([]);
              setLast("");
              setError("");
            }}
            className="w-full rounded-lg bg-teal-300 p-3 text-sm font-semibold text-slate-950"
          >
            New conversation
          </button>
          <h2 className="mt-6 text-sm text-slate-400">Saved conversations</h2>
          <div className="mt-3 space-y-2">
            {sessions.map((s) => (
              <button
                key={s.id}
                disabled={busy}
                aria-current={selected?.id === s.id ? "true" : undefined}
                onClick={() => open(s)}
                className="block w-full truncate rounded-lg border border-slate-700 p-3 text-left text-xs hover:border-teal-300"
              >
                {s.provider} · {s.id.slice(0, 8)}
              </button>
            ))}
          </div>
          {hasMore && (
            <button
              disabled={busy}
              onClick={() =>
                refresh(sessions.length).catch((e) => setError(e.message))
              }
              className="mt-4 text-sm text-teal-300"
            >
              Load more
            </button>
          )}
        </aside>
        <section className="min-w-0 rounded-xl border border-slate-800 p-5">
          <div className="flex flex-wrap items-end gap-4">
            <label className="text-sm">
              Provider
              <select
                aria-label="Provider"
                disabled={busy || !!selected}
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="mt-2 block rounded-lg border border-slate-700 bg-slate-950 p-3"
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id} disabled={!p.enabled}>
                    {p.id}
                    {!p.enabled ? " (disabled)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              Model
              <select
                aria-label="Model"
                disabled={busy || !!selected}
                className="mt-2 block max-w-full rounded-lg border border-slate-700 bg-slate-950 p-3"
              >
                <option>{current?.model || "Loading…"}</option>
              </select>
            </label>
            <button
              disabled={busy}
              onClick={clear}
              className="rounded-lg border border-slate-700 p-3 text-sm"
            >
              Clear conversation
            </button>
          </div>
          {current && !current.configured && (
            <p className="mt-4 text-sm text-amber-200">
              Groq is not configured. Add the API key securely to the backend
              environment; free-tier limits apply.
            </p>
          )}
          {error && (
            <div className="mt-4 rounded-lg border border-red-900 p-3">
              <p role="alert" className="break-words text-sm text-red-200">
                {error}
              </p>
              <button
                disabled={busy}
                onClick={() => (last ? send(last) : window.location.reload())}
                className="mt-2 text-sm text-teal-300"
              >
                Retry
              </button>
            </div>
          )}
          <div
            aria-label="Conversation history"
            className="my-5 max-h-[55vh] space-y-4 overflow-auto rounded-lg bg-slate-950/60 p-4"
          >
            {!messages.length && (
              <p className="py-10 text-center text-sm text-slate-400">
                Start a task. No shell or sandbox execution is available.
              </p>
            )}
            {messages.map((m) => (
              <article
                key={m.id}
                className="space-y-3 border-b border-slate-800 pb-5"
              >
                <p className="text-xs text-teal-300">You</p>
                <p className="whitespace-pre-wrap break-words text-sm">
                  {m.user_content}
                </p>
                <p className="text-xs text-slate-400">Assistant · {m.status}</p>
                <p className="whitespace-pre-wrap break-words text-sm leading-6">
                  {m.assistant_content ||
                    "Execution interrupted. Retry this task."}
                </p>
                <details>
                  <summary className="cursor-pointer text-xs text-teal-300">
                    Tool execution timeline
                  </summary>
                  <ol className="mt-3 space-y-2">
                    {m.events.map((event, i) => (
                      <li
                        key={i}
                        className="break-words rounded bg-slate-900 p-2 text-xs text-slate-300"
                      >
                        {event.kind}
                        {event.tool ? ` · ${event.tool}` : ""}
                        {event.input && (
                          <pre className="whitespace-pre-wrap">
                            Input: {event.input}
                          </pre>
                        )}
                        {event.output && (
                          <pre className="whitespace-pre-wrap">
                            Output: {event.output}
                          </pre>
                        )}
                      </li>
                    ))}
                  </ol>
                </details>
              </article>
            ))}
          </div>
          <form onSubmit={submit}>
            <label htmlFor="task" className="text-sm">
              Task or instructions
            </label>
            <textarea
              id="task"
              required
              maxLength={4000}
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={busy || !ready}
              rows={3}
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm"
              placeholder="Calculate (12 + 8) / 2, summarize text, or ask a question…"
            />
            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="text-xs text-slate-500">
                {text.length}/4000 · Never enter credentials or sensitive data.
              </p>
              <button
                disabled={busy || !ready || !text.trim()}
                type="submit"
                className="rounded-lg bg-teal-300 px-5 py-3 text-sm font-semibold text-slate-950 disabled:opacity-50"
              >
                {busy ? "Working…" : "Send message"}
              </button>
            </div>
          </form>
        </section>
      </div>
    </main>
  );
}
