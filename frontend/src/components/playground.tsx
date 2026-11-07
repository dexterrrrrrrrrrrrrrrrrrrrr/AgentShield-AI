"use client";
import Link from "next/link";
import SafeMarkdown from "./safe-markdown";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError } from "@/lib/protected-api";
import { agentApi } from "@/lib/agent-client";

type Provider = {
  id: string;
  model: string;
  enabled: boolean;
  configured: boolean;
};
type Session = {
  id: string;
  provider: string;
  model: string;
  status: string;
  allowed_tools: string[];
};
type Event = { kind: string; tool?: string; input?: string; output?: string; status?: string; approved?: boolean; duration?: number };
type Turn = {
  id: string;
  user_content: string;
  assistant_content: string;
  status: string;
  events: Event[];
  pending_execution_ids?: string[];
};

export default function Playground() {
  const router = useRouter();
  const search = useSearchParams();
  const requestedSession = search.get("session");
  const opening = useRef(0);
  const configurationLoaded = useRef(false);
  const clearDialog = useRef<HTMLDialogElement>(null);
  const [tools, setTools] = useState<string[]>([]);
  const [allowedTools, setAllowedTools] = useState<string[]>([]);
  const [uncertain, setUncertain] = useState(false);
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
  const awaitingApproval = messages.some(
    (m) => m.status === "awaiting_approval",
  );

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
          setTools(p.tools);
          if (!configurationLoaded.current) setAllowedTools(p.tools);
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

  const open = useCallback(async (session: Pick<Session, "id">) => {
    const request = ++opening.current;
    setBusy(true);
    setError("");
    setSelected(null);
    setMessages([]);
    setLast("");
    setUncertain(false);
    try {
      const data = await agentApi(`/sessions/${session.id}/messages?limit=50`);
      if (request !== opening.current) return;
      setSelected(data.session);
      setProvider(data.session.provider);
      configurationLoaded.current = true;
      setAllowedTools(data.session.allowed_tools);
      setMessages(data.messages);
      const last = data.messages.at(-1);
      setError(last?.status === "failed" ? last.assistant_content : "");
      setLast(last?.status === "failed" ? last.user_content : "");
      setUncertain(false);
    } catch (e) {
      if (request === opening.current)
        setError(
          e instanceof Error ? e.message : "Unable to load conversation",
        );
    } finally {
      if (request === opening.current) setBusy(false);
    }
  }, []);
  useEffect(() => {
    if (!requestedSession || !/^[a-f0-9]{32}$/.test(requestedSession)) return;
    const timer = setTimeout(() => void open({ id: requestedSession }), 0);
    return () => clearTimeout(timer);
  }, [requestedSession, open]);
  async function send(content: string) {
    if (!content.trim() || !current || awaitingApproval) return;
    setBusy(true);
    setError("");
    setLast(content);
    setUncertain(false);
    try {
      const session =
        selected ||
        (await agentApi("/sessions", "POST", {
          provider,
          model: current.model,
          allowed_tools: allowedTools,
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
      router.replace(`/playground?session=${session.id}`);
    } catch (e) {
      setUncertain(
        e instanceof ApiError && [0, 502, 503, 504].includes(e.status),
      );
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
      ++opening.current;
      setSelected(null);
      router.replace("/playground");
      setMessages([]);
      setLast("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to clear conversation");
    } finally {
      setBusy(false);
    }
  }
  async function resolve(turn: Turn) {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const result = await agentApi(
        `/sessions/${selected.id}/messages/${turn.id}/resolve`,
        "POST",
      );
      setMessages((old) => old.map((m) => (m.id === result.id ? result : m)));
      setUncertain(false);
      setLast("");
      if (result.status === "failed") setError(result.assistant_content);
      await refresh();
    } catch (e) {
      setUncertain(
        e instanceof ApiError && [0, 502, 503, 504].includes(e.status),
      );
      setError(
        e instanceof Error ? e.message : "Unable to resolve the execution",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="mx-auto max-w-6xl px-5 py-8">
      <header className="my-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-xs tracking-widest text-teal-300">
            AGENTSHIELD AI · AGENT OPERATIONS
          </p>
          <h1 className="mt-2 text-3xl font-semibold">Agent Playground</h1>
          <p className="mt-2 text-sm text-slate-400">
            Conversations with bounded tools, policy checks, and human approval
            for sensitive actions.
          </p>
        </div>
        <p role="status" aria-live="polite" className="text-sm text-teal-300">
          {busy
            ? "Working…"
            : !ready
              ? "Loading…"
              : awaitingApproval
                ? "Awaiting human approval"
                : "Ready"}
        </p>
      </header>
      <div className="playground-grid">
        <aside
          aria-label="Conversations"
          className="rounded-xl border border-slate-800 bg-[#0d1422] p-4"
        >
          <button
            disabled={busy}
            onClick={() => {
              ++opening.current;
              setSelected(null);
              router.replace("/playground");
              setMessages([]);
              setLast("");
              setError("");
              setUncertain(false);
            }}
            className="w-full rounded-lg bg-teal-300 p-3 text-sm font-semibold text-slate-950"
          >
            New conversation
          </button>
          <h2 className="mt-6 text-sm text-slate-400">Saved conversations</h2>
          {!ready && (
            <div
              aria-label="Loading conversations"
              aria-busy="true"
              className="mt-3 h-16 rounded bg-slate-900"
            />
          )}
          {ready && !sessions.length && (
            <p className="mt-3 text-xs text-slate-500">
              No saved conversations yet.
            </p>
          )}
          <div className="mt-3 space-y-2">
            {sessions.map((s) => (
              <button
                key={s.id}
                disabled={busy}
                aria-current={selected?.id === s.id ? "true" : undefined}
                onClick={() => router.push(`/playground?session=${s.id}`)}
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
        <section className="chat-surface">
          <details open className="chat-settings"><summary>Provider, model & tool permissions</summary>
          <div className="mt-4 flex flex-wrap items-end gap-4">
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
                <option>
                  {selected?.model || current?.model || "Loading…"}
                </option>
              </select>
            </label>
            <button
              disabled={busy || !selected}
              onClick={() => clearDialog.current?.showModal()}
              className="rounded-lg border border-slate-700 p-3 text-sm"
            >
              Clear conversation
            </button>
          </div>
          <fieldset
            disabled={busy || !!selected || !ready}
            aria-label="Tool permissions"
            className="mt-5 rounded-lg border border-slate-800 p-4"
          >
            <legend className="px-2 text-sm text-slate-300">
              Tool permissions
            </legend>
            <p className="mb-3 text-xs text-slate-500">
              Choose the server-supported tools for this conversation. Saved
              permissions are locked; create a new conversation to change them.
            </p>
            <div className="flex flex-wrap gap-x-5 gap-y-3">
              {tools.map((tool) => (
                <label key={tool} className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    aria-label={tool}
                    checked={allowedTools.includes(tool)}
                    onChange={(e) =>
                      setAllowedTools((old) =>
                        e.target.checked
                          ? [...old, tool]
                          : old.filter((t) => t !== tool),
                      )
                    }
                  />
                  {tool}
                </label>
              ))}
            </div>
          </fieldset>
          </details>
          {selected && current && selected.model !== current.model && <p className="mb-4 text-sm text-amber-200">This conversation uses saved model {selected.model}. New conversations use {current.model}. Create a new conversation to use the current deployment model.</p>}
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
                onClick={() =>
                  uncertain && selected
                    ? open(selected)
                    : last
                      ? send(last)
                      : window.location.reload()
                }
                className="mt-2 text-sm text-teal-300"
              >
                {uncertain ? "Reload conversation" : "Retry"}
              </button>
            </div>
          )}
          <div
            aria-label="Conversation history"
            className="chat-history my-5 space-y-4 overflow-auto rounded p-4"
          >
            {!messages.length && (
              <p className="py-10 text-center text-sm text-slate-400">
                Start a task. Tools follow your allowlist; code execution
                requires verified sandbox isolation and policy approval.
              </p>
            )}
            {messages.map((m) => (
              <article
                key={m.id}
                className="space-y-3 border-b border-slate-800 pb-5"
              >
                <div className="user-message"><p className="message-label">You</p><p className="whitespace-pre-wrap break-words text-sm">{m.user_content}</p></div>
                <div className="assistant-message"><p className="message-label">Assistant · {m.status}</p><SafeMarkdown text={m.assistant_content || "Execution interrupted. Retry this task."} /></div>
                {m.status === "completed" && !m.events.some((event) => event.kind === "tool_request") && (
                  <p className="text-xs text-slate-400">
                    No tool request was recorded for this turn. The model can answer directly even when tools are enabled.
                  </p>
                )}
                {m.status === "awaiting_approval" && (
                  <section className="rounded border border-amber-800 bg-amber-950/20 p-4">
                    <h2 className="text-sm font-medium text-amber-200">
                      Human approval required
                    </h2>
                    <p className="mt-2 text-xs text-slate-400">
                      Review the exact request and approve or reject it in
                      Monitoring. Then continue this original turn; resolving
                      never replays the code.
                    </p>
                    <div className="mt-3 flex flex-wrap gap-4">
                      {m.pending_execution_ids?.map((id) => (
                        <Link
                          key={id}
                          href={`/monitoring?execution=${id}`}
                          className="text-sm text-teal-300"
                        >
                          Review approval
                        </Link>
                      ))}
                      <button
                        disabled={busy}
                        onClick={() => void resolve(m)}
                        className="text-sm text-teal-300"
                      >
                        Continue after decision
                      </button>
                    </div>
                  </section>
                )}
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
                        {event.status && <p>Execution: {event.status}</p>}
                        {event.approved !== undefined && <p>Approval: {event.approved ? "Approved" : "Not approved"}</p>}
                        {typeof event.duration === "number" && Number.isFinite(event.duration) && <p>Duration: {event.duration.toFixed(3)} s</p>}
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
          <form onSubmit={submit} className="chat-composer">
            <label htmlFor="task" className="text-sm">
              Task or instructions
            </label>
            <textarea
              id="task"
              required
              maxLength={4000}
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={busy || !ready || awaitingApproval}
              rows={3}
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm"
              placeholder="Calculate (12 + 8) / 2, summarize text, or ask a question…"
            />
            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="text-xs text-slate-500">
                {text.length}/4000 · Never enter credentials or sensitive data.
              </p>
              <button
                disabled={busy || !ready || awaitingApproval || !text.trim()}
                type="submit"
                className="rounded-lg bg-teal-300 px-5 py-3 text-sm font-semibold text-slate-950 disabled:opacity-50"
              >
                {busy ? "Working…" : "Send message"}
              </button>
            </div>
          </form>
        </section>
      </div>
      <dialog
        ref={clearDialog}
        aria-labelledby="clear-title"
        className="m-auto max-w-md rounded-xl border border-slate-700 bg-[#0d1422] p-6 text-slate-100 backdrop:bg-black/70"
      >
        <h2 id="clear-title" className="text-xl font-semibold">
          Clear conversation?
        </h2>
        <p className="mt-3 text-sm leading-6 text-slate-400">
          This deletes the selected conversation and its messages. Security
          audit and sandbox history follow their retention policies.
        </p>
        <div className="mt-6 flex gap-4">
          <button
            onClick={() => clearDialog.current?.close()}
            className="rounded border border-slate-700 px-4 py-2 text-sm"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              clearDialog.current?.close();
              void clear();
            }}
            className="rounded bg-red-300 px-4 py-2 text-sm font-semibold text-slate-950"
          >
            Delete conversation
          </button>
        </div>
      </dialog>
    </main>
  );
}
