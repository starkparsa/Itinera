import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { auth } from "@/auth";
import { getProfile, getPassport } from "@/lib/backend";
import RouteErrorState from "@/components/RouteErrorState";
import ProfileEditorButton from "@/components/onboarding/ProfileEditorButton";
import DeleteAccountButton from "@/components/onboarding/DeleteAccountButton";
import PassportBadges from "@/components/gamification/PassportBadges";

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="text-sm">{value || <span className="text-muted-foreground">Not set</span>}</span>
    </div>
  );
}

export default async function ProfilePage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  const [profile, passport] = await Promise.all([getProfile(), getPassport()]);

  return (
    <main id="main-content" className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-4 py-6 md:px-8">
      <Link href="/" className="mb-1 flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-3.5" /> Back to chat
      </Link>
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold">Your profile</h1>
        {profile && <ProfileEditorButton profile={profile} userEmail={session.user.email ?? null} />}
      </div>

      {!profile ? (
        <RouteErrorState message="Couldn't load your profile." retryHref="/profile" />
      ) : (
        <div className="my-6 flex flex-col gap-8">
          <section className="flex flex-col gap-4">
            <h2 className="text-sm font-semibold text-muted-foreground">Account details</h2>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Name" value={profile.display_name} />
              <Field label="Email" value={session.user.email} />
              <Field label="Mobile number" value={profile.mobile_number} />
              <Field label="Date of birth" value={profile.date_of_birth} />
              <Field label="Country / region" value={profile.country_region} />
            </div>
          </section>

          <section className="flex flex-col gap-4">
            <h2 className="text-sm font-semibold text-muted-foreground">Trip style</h2>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Travel frequency" value={profile.travel_frequency} />
              <Field label="Pace" value={profile.pace} />
              <Field label="Interests" value={profile.interests.join(", ")} />
            </div>
          </section>

          <section className="flex flex-col gap-4">
            <h2 className="text-sm font-semibold text-muted-foreground">Habits &amp; logistics</h2>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Budget comfort" value={profile.budget_tier} />
              <Field label="Usually travels with" value={profile.travel_companions} />
              <Field label="Typical trip length" value={profile.typical_trip_length_days ? `${profile.typical_trip_length_days} days` : null} />
              <Field label="Dietary needs" value={profile.dietary_needs} />
            </div>
          </section>

          <section className="flex flex-col gap-4">
            <h2 className="text-sm font-semibold text-muted-foreground">Goals</h2>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Accessibility needs" value={profile.accessibility_needs} />
              <Field label="On your list" value={profile.bucket_list_countries.join(", ")} />
            </div>
          </section>

          <section className="flex flex-col gap-4">
            <h2 className="text-sm font-semibold text-muted-foreground">Your passport</h2>
            <PassportBadges passport={passport} />
          </section>

          <section className="flex flex-col gap-3 rounded-lg border border-destructive/30 p-4">
            <div>
              <h2 className="text-sm font-semibold text-destructive">Danger zone</h2>
              <p className="text-sm text-muted-foreground">
                Permanently delete your account, trips, chat history, and profile answers. This can&apos;t be
                undone.
              </p>
            </div>
            <div>
              <DeleteAccountButton />
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
