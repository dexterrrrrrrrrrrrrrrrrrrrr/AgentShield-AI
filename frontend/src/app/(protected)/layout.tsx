import { authenticatedUser } from "@/lib/auth-server";
import WorkspaceNav from "@/components/workspace-nav";
import { SessionProvider } from "@/components/session";

export const dynamic = "force-dynamic";
export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await authenticatedUser();
  if (!user)
    return (
      <main className="mx-auto max-w-xl px-6 py-20">
        <h1 className="text-2xl font-semibold">
          Workspace temporarily unavailable
        </h1>
        <p role="alert" className="mt-4 text-slate-400">
          We could not verify your session. Check the backend connection and
          reload this page.
        </p>
      </main>
    );
  return <SessionProvider user={user}><div className="workspace-shell"><WorkspaceNav /><div id="workspace-content" tabIndex={-1} className="workspace-content">{children}</div></div></SessionProvider>;
}
