import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { User } from "./auth-client";

export async function authenticatedUser(): Promise<User | null> {
  const jar = await cookies();
  const session =
    jar.get("__Host-agentshield_session") ?? jar.get("agentshield_session");
  if (!session) redirect("/login");
  let response: Response;
  try {
    const base = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";
    response = await fetch(`${base}/api/auth/me`, {
      headers: { Cookie: `${session.name}=${session.value}` },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
  } catch {
    return null;
  }
  if (response.status === 401) redirect("/login");
  if (!response.ok) return null;
  return response.json() as Promise<User>;
}
