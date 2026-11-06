import Profile from "@/components/profile";

export default async function ProfilePage({
  searchParams,
}: {
  searchParams: Promise<{ oauth_error?: string; google?: string }>;
}) {
  const params = await searchParams;
  return <Profile oauthError={params.oauth_error} linked={params.google === "linked"} />;
}
