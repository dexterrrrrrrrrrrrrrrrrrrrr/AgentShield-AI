import type { Metadata } from "next";
import "./globals.css";
import localFont from "next/font/local";
const heading = localFont({ src: "./fonts/SpaceGrotesk.ttf", variable: "--font-heading", display: "swap" });
const mono = localFont({ src: "./fonts/JetBrainsMono.ttf", variable: "--font-code", display: "swap" });
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
      <body className={`${heading.variable} ${mono.variable}`}>{children}</body>
    </html>
  );
}
