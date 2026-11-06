import AuthForm from "@/components/auth-form";
export default async function Login({
  searchParams,
}: {
  searchParams: Promise<{ registered?: string; oauth_error?: string }>;
}) {
  const params = await searchParams;
  return (
    <>
      {params.registered === "1" && (
        <p
          role="status"
          className="absolute top-4 right-4 left-4 text-center text-sm text-teal-300"
        >
          Account created. Sign in to continue.
        </p>
      )}
      <AuthForm mode="login" oauthError={params.oauth_error} />
    </>
  );
}
