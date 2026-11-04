import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "AgentShield AI",
  description: "AI agent security workspace — Phase 2 secure accounts",
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
