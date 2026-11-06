"use client";
import WorkspaceNav from "./workspace-nav";
import CodeEditor from "./code-editor";
import { protectedApi } from "@/lib/protected-api";
import { languageName, registeredLanguage, STARTER_CODE, type LanguageId } from "@/lib/languages";
import { useEffect, useState } from "react";

type Language = { id: string; display_name: string; extension: string; version: string; compilation_required: boolean; limits: Record<string, number> };
type Execution = {
  id: string; language?: string; status: string; policy_decision: string; request_hash: string;
  stdout: string; stderr: string; exit_code: number | null; duration: number | null;
  execution_duration_ms?: number | null; compile_status?: string; compile_stdout?: string; compile_stderr?: string;
  error_category?: string; approval_request?: { language?: string; code: string; stdin?: string };
  limits?: Record<string, number>;
};
function api(path: string, body?: unknown) { return protectedApi(`/sandbox${path}`, body === undefined ? "GET" : "POST", body); }
function historyPath(offset: number, filter: string) { return `/executions?offset=${offset}&limit=20${filter ? `&language=${encodeURIComponent(filter)}` : ""}`; }
const smallButton = "rounded border border-slate-700 px-4 py-2 text-sm disabled:opacity-40";

export default function Sandbox() {
  const [language, setLanguage] = useState<LanguageId>("python");
  const [executionPolicy, setExecutionPolicy] = useState("REQUIRE_APPROVAL");
  const [languages, setLanguages] = useState<Language[]>([]);
  const [drafts, setDrafts] = useState(STARTER_CODE);
  const [stdin, setStdin] = useState("");
  const [ready, setReady] = useState(false);
  const [checking, setChecking] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [pageOffset, setPageOffset] = useState(0);
  const [filter, setFilter] = useState("");
  const [historyLoading, setHistoryLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [readinessMessage, setReadinessMessage] = useState("");
  const [history, setHistory] = useState<Execution[]>([]);
  const [selected, setSelected] = useState<Execution | null>(null);
  const [more, setMore] = useState(false);
  const code = drafts[language];
  const configuration = languages.find((entry) => entry.id === language);
  useEffect(() => {
    let live = true;
    api("/languages").then((data) => { if (live) { setLanguages(data.languages); setExecutionPolicy(data.execution_policy || "REQUIRE_APPROVAL"); } }).catch((cause) => { if (live) setError(cause.message); });
    return () => { live = false; };
  }, []);
  useEffect(() => {
    let live = true;
    api(`/readiness?language=${language}`).then((data) => {
      if (live) { setReady(data.ready); setReadinessMessage(typeof data.message === "string" ? data.message : ""); setChecking(false); }
    }).catch((cause) => { if (live) { setReady(false); setChecking(false); setError(cause.message); } });
    return () => { live = false; };
  }, [language, attempt]);
  useEffect(() => {
    let live = true;
    api(historyPath(0, filter)).then((data) => {
      if (live) { setHistory(data.executions); setPageOffset(0); setMore(data.executions.length === 20); setHistoryLoading(false); }
    }).catch((cause) => { if (live) { setHistoryLoading(false); setError(cause.message); } });
    return () => { live = false; };
  }, [filter]);
  async function load(offset = 0) {
    const data = await api(historyPath(offset, filter));
    setHistory(data.executions); setPageOffset(offset); setMore(data.executions.length === 20);
  }
  async function perform(action: () => Promise<Execution>) {
    setBusy(true); setError("");
    try {
      const result = await action();
      if (result.status === "unavailable" && (result.language || "python") === language) setReady(false);
      setSelected(await api(`/executions/${result.id}`));
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Sandbox request failed"); }
    finally { setBusy(false); }
  }
  const bytes = new TextEncoder().encode(code).length;
  const inputBytes = new TextEncoder().encode(stdin).length;
  return (
    <main className="mx-auto max-w-6xl px-5 py-8">
      <WorkspaceNav />
      <h1 className="mt-5 text-3xl font-semibold">Code Sandbox</h1>
      <p className="mt-3 text-sm text-slate-400">{executionPolicy === "AUTO_EXECUTE" ? "Trusted local automatic execution. Run Code starts an isolated job without an approval step." : "Isolated code execution with deterministic policy and explicit approvals."} Compilation stays inside the sandbox. Never enter secrets.</p>
      <p role="status" className="mt-5 rounded-lg border border-slate-700 p-4 text-sm">
        {checking ? `Checking ${languageName(language)} sandbox isolation…` : busy ? "Running..." : ready ? `${languageName(language)} sandbox readiness checks passed` : "SANDBOX_UNAVAILABLE · Execution is disabled until effective isolation checks pass."}
        {!checking && !ready && readinessMessage && <span className="mt-2 block text-slate-400">{readinessMessage}</span>}
      </p>
      <button disabled={busy || checking} onClick={() => { setChecking(true); setReady(false); setAttempt((value) => value + 1); }} className={`mt-3 ${smallButton}`}>Refresh sandbox status</button>
      {error && <p role="alert" className="mt-4 text-red-300">{error}</p>}
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_240px]">
        <section className="min-w-0">
          <label htmlFor="language" className="block text-sm">Language</label>
          <select id="language" value={language} disabled={busy} onChange={(event) => {
            if (registeredLanguage(event.target.value) && event.target.value !== language) { setLanguage(event.target.value); setReady(false); setChecking(true); setError(""); }
          }} className="mt-2 mb-4 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm">
            {(languages.length ? languages.filter((entry) => registeredLanguage(entry.id)) : [{ id: "python", display_name: "Python" }]).map((entry) => <option key={entry.id} value={entry.id}>{entry.display_name}</option>)}
          </select>
          <CodeEditor value={code} onChange={(value) => setDrafts((old) => ({ ...old, [language]: value }))} label={`${languageName(language)} code`} disabled={busy} />
          <p className="mt-2 text-xs text-slate-400">{bytes}/32768 source bytes{configuration ? ` · ${configuration.version} · ${configuration.compilation_required ? "Compilation required" : "Interpreted runtime"}` : ""}</p>
          {configuration && <p className="mt-2 text-xs text-slate-400">{configuration.limits.memory_mb} MiB · {configuration.limits.cpus} CPU · {configuration.limits.pids} PIDs · {configuration.limits.timeout} seconds execution limit</p>}
          <label htmlFor="stdin" className="mt-5 block text-sm">Standard input (optional)</label>
          <textarea id="stdin" value={stdin} onChange={(event) => setStdin(event.target.value)} disabled={busy} rows={3} maxLength={8192} spellCheck={false} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 font-mono text-sm" />
          <p className="mt-1 text-xs text-slate-400">{inputBytes}/8192 input bytes · Sent as input data, never as commands.</p>
          <div className="mt-4 flex flex-wrap gap-3">
            <button disabled={busy || checking || !ready || executionPolicy === "DENY" || !configuration || bytes > 32768 || inputBytes > 8192 || !code.trim()} onClick={() => perform(() => api("/execute", { language, source_code: code, stdin, tool: "execute_code" }))} className="rounded-lg bg-teal-300 px-5 py-3 font-semibold text-slate-950 disabled:opacity-40">{busy ? "Running..." : "Run Code"}</button>
            <button disabled={busy || !selected} onClick={() => setSelected(null)} className={smallButton}>Clear Output</button>
          </div>
          {selected && <article className="mt-6 space-y-4 rounded-xl border border-slate-800 p-5">
            <h2 className="text-lg">Execution {selected.id.slice(0, 8)} · {languageName(selected.language)}</h2>
            <p>Status: {selected.status} · Policy: {selected.policy_decision}</p>
            {executionPolicy === "AUTO_EXECUTE" && selected.status === "pending_approval" && <p className="text-sm text-amber-300">This older request was not executed automatically. Review it in Monitoring or submit a new request.</p>}
            {selected.error_category && <p role="alert">{selected.error_category}</p>}
            <p className="text-sm">Exit code: {selected.exit_code ?? "—"} · Duration: {selected.execution_duration_ms != null ? `${selected.execution_duration_ms} ms` : selected.duration != null ? `${selected.duration} seconds` : "—"} · Compilation: {selected.compile_status || "not_required"}</p>
            {executionPolicy !== "AUTO_EXECUTE" && selected.approval_request && selected.status === "pending_approval" && <section className="rounded border border-amber-700 p-4">
              <h3 className="font-semibold">Review exact execution request</h3>
              <p className="mt-2 text-sm">Language: {languageName(selected.approval_request.language)}. Approval rechecks permissions and isolation for this request.</p>
              <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs">{selected.approval_request.code}</pre>
              <h4 className="mt-3 text-sm">Standard input</h4>
              <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words text-xs">{selected.approval_request.stdin || "(empty)"}</pre>
              <p className="mt-3 break-all text-xs text-slate-400">Request hash: {selected.request_hash}</p>
              <pre className="mt-3 text-xs">{JSON.stringify(selected.limits, null, 2)}</pre>
              <div className="mt-4 flex flex-wrap gap-3">
                <button disabled={busy} onClick={() => perform(() => api(`/approvals/${selected.id}`, { approve: true, request_hash: selected.request_hash }))} className="rounded border border-amber-400 px-4 py-2 text-sm disabled:opacity-40">Approve exact request once</button>
                <button disabled={busy} onClick={() => perform(() => api(`/approvals/${selected.id}/reject`, { reject: true, request_hash: selected.request_hash }))} className="rounded border border-red-700 px-4 py-2 text-sm text-red-300 disabled:opacity-40">Reject exact request</button>
              </div>
            </section>}
            {selected.compile_status && selected.compile_status !== "not_required" && <section>
              <h3>Compilation output</h3>
              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words bg-slate-950 p-3 text-xs">{selected.compile_stdout || selected.compile_stderr ? [selected.compile_stdout, selected.compile_stderr].filter(Boolean).join("\n") : "(empty)"}</pre>
            </section>}
            <h3>stdout</h3><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words bg-slate-950 p-3 text-xs">{selected.stdout || "(empty)"}</pre>
            <h3>stderr</h3><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words bg-slate-950 p-3 text-xs">{selected.stderr || "(empty)"}</pre>
          </article>}
        </section>
        <aside className="min-w-0 rounded-xl border border-slate-800 p-4">
          <h2 className="text-sm">Execution history</h2>
          <label htmlFor="history-language" className="mt-4 block text-xs text-slate-400">Filter by language</label>
          <select id="history-language" value={filter} disabled={busy} onChange={(event) => { setFilter(event.target.value); setHistoryLoading(true); }} className="mt-2 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm">
            <option value="">All languages</option>{languages.map((entry) => <option key={entry.id} value={entry.id}>{entry.display_name}</option>)}
          </select>
          {historyLoading && <div aria-label="Loading execution history" aria-busy="true" className="mt-4 h-16 rounded bg-slate-900" />}
          {!historyLoading && !history.length && <p className="mt-4 text-xs text-slate-400">No executions recorded.</p>}
          <div className="mt-4 space-y-3">{history.map((entry) => <button key={entry.id} disabled={busy || historyLoading} onClick={() => perform(() => api(`/executions/${entry.id}`))} className="block w-full rounded border border-slate-700 p-3 text-left text-xs disabled:opacity-40">{entry.id.slice(0, 8)} · {languageName(entry.language)} · {entry.status}</button>)}</div>
          {pageOffset > 0 && <button disabled={busy || historyLoading} onClick={() => load(Math.max(0, pageOffset - 20)).catch((cause) => setError(cause.message))} className="mt-4 text-sm text-teal-300">Newer executions</button>}
          {more && <button disabled={busy || historyLoading} onClick={() => load(pageOffset + 20).catch((cause) => setError(cause.message))} className="mt-4 text-sm text-teal-300">Load more</button>}
        </aside>
      </div>
    </main>
  );
}
