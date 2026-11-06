"use client";
import Image from "next/image";
import { useUser } from "@/components/session";
import GoogleButton from "@/components/google-button";
import { oauthErrorMessage } from "@/lib/auth-client";

function safePicture(value?: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (
      url.protocol === "https:" &&
      !url.username && !url.password && !url.port &&
      (url.hostname === "googleusercontent.com" || url.hostname.endsWith(".googleusercontent.com"))
    ) return url.href;
  } catch { /* Omit malformed external image URLs. */ }
  return null;
}

export default function Profile({ oauthError, linked }: { oauthError?: string; linked: boolean }) {
  const user = useUser();
  const picture = safePicture(user.profile_picture);
  const providers = {
    password: "Email and password",
    google: "Google",
    "password+google": "Email and password · Google",
  };
  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <section className="mt-7 rounded-2xl border border-slate-800 bg-[#0d1422] p-7">
        <p className="text-xs font-semibold tracking-widest text-teal-300">YOUR ACCOUNT</p>
        <div className="mt-3 flex items-center gap-5">
          {picture && (
            <Image
              unoptimized
              src={picture}
              alt="Google profile picture"
              width={64}
              height={64}
              referrerPolicy="no-referrer"
              className="rounded-full"
            />
          )}
          <h1 className="text-3xl font-semibold">Profile</h1>
        </div>
        {oauthError && <p role="alert" className="mt-5 rounded-lg border border-amber-800 p-3 text-sm text-amber-100">{oauthErrorMessage(oauthError)}</p>}
        {linked && user.google_connected && <p role="status" className="mt-5 rounded-lg border border-teal-800 p-3 text-sm text-teal-200">Google account connected successfully.</p>}
        <dl className="profile-details my-8">
          {[
            ["Full name", user.full_name],
            ["Email", user.email],
            ["Email verification", user.email_verified ? "Verified" : "Not verified"],
            ["Sign-in methods", providers[user.authentication_provider || "password"]],
            ["Google account", user.google_connected ? "Connected" : "Not connected"],
            ["Account created", new Date(user.created_at).toISOString().slice(0, 10) + " (UTC)"],
            ["Authentication status", "Authenticated"],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-sm text-slate-400">{label}</dt>
              <dd className="mt-2 break-words text-lg">{value}</dd>
            </div>
          ))}
        </dl>
        {!user.google_connected && user.authentication_provider !== "google" && (
          <section aria-label="Connect Google" className="mb-7 rounded-xl border border-slate-700 p-4">
            <h2 className="mb-3 font-semibold">Connect another sign-in method</h2>
            <GoogleButton mode="link" />
            <p className="mt-3 text-xs leading-5 text-slate-400">Google is connected only after you authorize it while signed in to this account. Matching email addresses do not link accounts automatically.</p>
          </section>
        )}
      </section>
    </main>
  );
}
