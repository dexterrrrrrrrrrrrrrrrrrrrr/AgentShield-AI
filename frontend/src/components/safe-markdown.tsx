"use client";
import { useState, type ReactNode } from "react";

// Intentionally small Markdown subset. HTML, images and links remain escaped text.
// No HTML insertion, remote resources or model-controlled navigation.
function inline(text: string): ReactNode[] {
  return text.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g).map((part, index) =>
    part.startsWith("`") && part.endsWith("`") ? <code key={index}>{part.slice(1,-1)}</code> :
    part.startsWith("**") && part.endsWith("**") ? <strong key={index}>{part.slice(2,-2)}</strong> : part);
}
function CodeBlock({ source, language }: { source: string; language: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  return <section className="code-block"><header><span>{language || "code"}</span><button onClick={async () => {
    try { await navigator.clipboard.writeText(source); setCopied(true); setFailed(false); }
    catch { setFailed(true); }
  }}>{copied ? "Copied" : "Copy code"}</button></header><pre><code>{source}</code></pre>{failed && <p role="status">Copy unavailable. Select the code to copy manually.</p>}</section>;
}
export default function SafeMarkdown({ text }: { text: string }) {
  const blocks = text.split(/(```[^\n]*\n[\s\S]*?```)/g);
  return <div className="safe-markdown">{blocks.map((block,i) => {
    if (block.startsWith("```")) {
      const end = block.indexOf("\n");
      return <CodeBlock key={i} language={block.slice(3,end).trim().slice(0,30)} source={block.slice(end+1,-3).replace(/\n$/, "")} />;
    }
    return block.split(/\n\n+/).filter(Boolean).map((paragraph,j) => {
      if (/^[-*] /m.test(paragraph) && paragraph.split("\n").every(line => /^[-*] /.test(line)))
        return <ul className="ml-5 list-disc" key={`${i}-${j}`}>{paragraph.split("\n").map((line,k) => <li key={k}>{inline(line.slice(2))}</li>)}</ul>;
      if (/^#{1,3} /.test(paragraph)) return <h3 className="my-3 text-lg" key={`${i}-${j}`}>{inline(paragraph.replace(/^#{1,3} /,""))}</h3>;
      return <p className="my-2" key={`${i}-${j}`}>{inline(paragraph)}</p>;
    });
  })}</div>;
}
