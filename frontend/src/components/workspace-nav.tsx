"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogoutButton } from "./session";

export default function WorkspaceNav({ logout = true }: { logout?: boolean }) {
  const path = usePathname();
  return (
    <header className="mb-7 flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-5">
      <nav
        aria-label="Workspace navigation"
        className="flex flex-wrap gap-x-5 gap-y-3 text-sm"
      >
        {[
          ["Dashboard", "/"],
          ["Playground", "/playground"],
          ["Sandbox", "/sandbox"],
          ["Monitoring", "/monitoring"],
          ["Settings", "/settings"],
          ["Profile", "/profile"],
        ].map(([name, href]) => (
          <Link
            key={href}
            href={href}
            aria-current={path === href ? "page" : undefined}
            className={
              path === href
                ? "font-semibold text-teal-300"
                : "text-slate-400 hover:text-white"
            }
          >
            {name}
          </Link>
        ))}
      </nav>
      {logout && <LogoutButton />}
    </header>
  );
}
