"use client";
import { useMemo, useRef } from "react";

// A bounded text overlay provides basic lexical highlighting. React escapes every
// token: source is never inserted as HTML, evaluated, or sent to another service.
function highlight(source: string) {
  const tokens = source.split(/("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\/\/[^\n]*|#[^\n]*|\b(?:class|public|static|void|int|return|const|let|var|function|if|else|while|for|import|from|def|print|new|string|number|boolean|true|false|None|True|False)\b|\b\d+(?:\.\d+)?\b)/g);
  return tokens.map((token, index) => {
    const color = /^['"]/.test(token) ? "text-amber-200" : /^(#|\/\/)/.test(token) ? "text-slate-500" : /^\d/.test(token) ? "text-blue-300" : /^(class|public|static|void|int|return|const|let|var|function|if|else|while|for|import|from|def|print|new|string|number|boolean|true|false|None|True|False)$/.test(token) ? "text-teal-300" : "";
    return <span key={index} className={color}>{token}</span>;
  });
}
export default function CodeEditor({ value, onChange, label, disabled }: {
  value: string; onChange: (value: string) => void; label: string; disabled: boolean;
}) {
  const preview = useRef<HTMLPreElement>(null);
  const gutter = useRef<HTMLDivElement>(null);
  const colored = useMemo(() => highlight(value), [value]);
  const style = "m-0 min-h-64 w-full whitespace-pre py-4 pr-4 pl-14 font-mono text-sm leading-6";
  return (
    <div>
      <label htmlFor="source-code" className="text-sm">{label}</label>
      <div className="editor-surface relative mt-2 overflow-hidden rounded focus-within:border-blue-400">
        <div ref={gutter} aria-hidden="true" className="editor-lines">{value.split("\n").map((_, i) => <div key={i}>{i+1}</div>)}</div>
        <pre ref={preview} aria-hidden="true" className={`pointer-events-none absolute inset-0 overflow-hidden text-slate-200 ${style}`}>{colored}{"\n"}</pre>
        <textarea id="source-code" value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}
          onScroll={(event) => { if (gutter.current) gutter.current.scrollTop = event.currentTarget.scrollTop; if (preview.current) { preview.current.scrollTop = event.currentTarget.scrollTop; preview.current.scrollLeft = event.currentTarget.scrollLeft; } }}
          rows={12} wrap="off" maxLength={32768} spellCheck={false} autoCapitalize="off" autoCorrect="off"
          className={`relative block resize-y bg-transparent text-transparent caret-white outline-none selection:bg-teal-800/60 ${style}`} />
      </div>
    </div>
  );
}
