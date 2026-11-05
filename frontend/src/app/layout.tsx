import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "AgentShield AI",
  description:
    "Security-first AI agents, controlled tools, human approvals, and signed audit trails",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
