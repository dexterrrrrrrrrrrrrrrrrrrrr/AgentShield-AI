import type { ReactNode } from "react";

export function PageHeader({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children?: ReactNode }) {
  return <header className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="page-description">{description}</p></div>{children}</header>;
}
export function StatusBadge({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "success" | "warning" | "error" }) {
  return <span className={`status-badge status-${tone}`}>{children}</span>;
}
export function MetricCard({ label, value, note }: { label: string; value: ReactNode; note: string }) {
  return <section className="metric-card"><h2>{label}</h2><p className="metric-value">{value}</p><p className="metric-note">{note}</p></section>;
}
export function Icon({ name }: { name: string }) {
  const paths: Record<string, string> = {
    arrow: "M5 19 19 5M7 5h12v12",
    shield: "M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7l-9-4Zm-4 9 3 3 5-6",
    Dashboard: "M3 3h7v7H3Zm11 0h7v7h-7ZM3 14h7v7H3Zm11 0h7v7h-7Z",
    Playground: "m4 6 6 6-6 6m9 0h7",
    Sandbox: "m8 5-6 7 6 7m8-14 6 7-6 7m-3-16-2 18",
    Monitoring: "M2 12h4l3-8 6 16 3-8h4",
    Settings: "M4 6h16M4 12h16M4 18h16M8 3v6m8 0v6m-6 0v6",
    Profile: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-3a8 8 0 0 1 16 0v3",
  };
  return <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="square" strokeLinejoin="miter"><path d={paths[name] || paths.shield} /></svg>;
}
