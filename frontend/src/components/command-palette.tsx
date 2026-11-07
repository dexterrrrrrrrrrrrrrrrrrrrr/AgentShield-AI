"use client";
import { useEffect, useId, useRef, useState } from "react";
import { useRouter } from "next/navigation";

export default function CommandPalette({ routes }: { routes: string[][] }) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const restore = useRef<HTMLElement | null>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const matches = routes.filter(([name]) => name.toLowerCase().includes(query.trim().toLowerCase()));
  function close() { dialog.current?.close(); }
  function open() {
    if (document.querySelector("dialog[open]")) return;
    restore.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setQuery(""); setActive(0); dialog.current?.showModal();
  }
  function navigate(href: string) { close(); router.push(href); }
  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k" && !event.altKey && !event.isComposing) {
        event.preventDefault();
        if (dialog.current?.open) dialog.current.close();
        else {
          if (document.querySelector("dialog[open]")) return;
          restore.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
          setQuery(""); setActive(0); dialog.current?.showModal();
        }
      }
    }
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, []);
  return <>
    <button type="button" className="command-trigger" onClick={open} aria-label="Open command palette" aria-haspopup="dialog">Quick navigation <kbd>⌘ / Ctrl K</kbd></button>
    <dialog ref={dialog} className="command-dialog" aria-label="Quick navigation" onClose={() => restore.current?.focus()} onClick={event => { if (event.target === event.currentTarget) close(); }}>
      <div className="command-inner">
        <div className="command-heading"><h2>Go to a page</h2><button type="button" onClick={close} aria-label="Close command palette">Esc</button></div>
        <label htmlFor={`${listId}-search`} className="sr-only">Search pages</label>
        <input id={`${listId}-search`} autoFocus role="combobox" aria-autocomplete="list" aria-expanded="true" aria-controls={listId} aria-activedescendant={matches.length ? `${listId}-${active}` : undefined} placeholder="Search pages…" value={query} onChange={event => { setQuery(event.target.value); setActive(0); }} onKeyDown={event => {
          if (event.nativeEvent.isComposing) return;
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault(); if (matches.length) setActive(index => (index + (event.key === "ArrowDown" ? 1 : -1) + matches.length) % matches.length);
          }
          if (event.key === "Enter" && matches[active]) { event.preventDefault(); navigate(matches[active][1]); }
        }} />
        <div id={listId} role="listbox" aria-label="Pages">{matches.map(([name, href], index) => <button type="button" role="option" id={`${listId}-${index}`} aria-selected={index === active} tabIndex={-1} key={href} onMouseMove={() => setActive(index)} onClick={() => navigate(href)}><span>{name}</span><span aria-hidden="true">↵</span></button>)}</div>
        {!matches.length && <p role="status" className="command-empty">No matching pages. Try another name.</p>}
        <p className="command-hint">↑ ↓ to choose · Enter to open · Escape to close</p>
      </div>
    </dialog>
  </>;
}
