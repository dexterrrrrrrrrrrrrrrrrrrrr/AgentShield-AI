"use client";
import WorkspaceNav from "@/components/workspace-nav";
import { LogoutButton, useUser } from "@/components/session";

export default function Profile() {
  const user = useUser();
  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <WorkspaceNav logout={false} />
      <section className="mt-7 rounded-2xl border border-slate-800 bg-[#0d1422] p-7">
        <p className="text-xs font-semibold tracking-widest text-teal-300">
          YOUR ACCOUNT
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Profile</h1>
        <dl className="my-8 space-y-6">
          {[
            ["Full name", user.full_name],
            ["Email", user.email],
            [
              "Account created",
              new Date(user.created_at).toISOString().slice(0, 10) + " (UTC)",
            ],
            ["Authentication status", "Authenticated"],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-sm text-slate-400">{label}</dt>
              <dd className="mt-2 break-words text-lg">{value}</dd>
            </div>
          ))}
        </dl>
        <LogoutButton />
      </section>
    </main>
  );
}
