"use client";
import Link from "next/link";
import CommandPalette from "./command-palette";
import { usePathname } from "next/navigation";
import { useRef } from "react";
import { LogoutButton, useUser } from "./session";
import { Icon } from "./ui";

const routes = [["Dashboard", "/"], ["Playground", "/playground"], ["Sandbox", "/sandbox"], ["Monitoring", "/monitoring"], ["Settings", "/settings"], ["Profile", "/profile"]];
export default function WorkspaceNav() {
  const path = usePathname();
  const user = useUser();
  const drawer = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  function close() { drawer.current?.close(); trigger.current?.focus(); }
  const navigation = <><Link href="/" className="brand" onClick={close}><span className="brand-mark"><Icon name="shield" /></span><span>AgentShield<span className="brand-ai"> / AI</span><small>SECURITY OPERATIONS</small></span></Link>
    <p className="nav-caption">WORKSPACE / 01</p>
    <nav aria-label="Workspace navigation">{routes.map(([label, href], i) => <Link key={href} href={href} onClick={close} aria-current={path === href ? "page" : undefined}><Icon name={label} /><span>{label}</span><span aria-hidden="true" className="nav-index">0{i + 1}</span></Link>)}</nav>
    <div className="nav-footer"><p className="eyebrow">CONTROLLED BY DESIGN</p><p>Scoped tools.<br />Observable execution.</p><Link href="/profile" className="account-link" onClick={close}>{user.full_name} · Profile</Link><LogoutButton /></div></>;
  return <><a className="skip-link" href="#workspace-content">Skip to content</a><aside className="desktop-sidebar">{navigation}</aside>
    <header className="workspace-topbar"><div className="flex items-center gap-3"><button className="drawer-toggle" ref={trigger} aria-label="Open navigation" onClick={() => drawer.current?.showModal()}>☰</button><span className="text-sm text-slate-400">Workspace <span className="px-2 text-blue-400">/</span> <span className="text-white">{routes.find(([,href]) => href === path)?.[0] || "Console"}</span></span></div><CommandPalette routes={routes} /><span className="identity-label"><span className="status-dot" />Authenticated session</span></header>
    <dialog ref={drawer} className="navigation-drawer" aria-label="Navigation menu" onClick={(e) => { if (e.target === e.currentTarget) close(); }}><div><button className="drawer-close" aria-label="Close navigation" onClick={close}>✕</button>{navigation}</div></dialog></>;
}
