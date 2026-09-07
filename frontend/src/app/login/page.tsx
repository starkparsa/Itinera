import { redirect } from "next/navigation";
import { auth, signIn } from "@/auth";
import { Button } from "@/components/ui/button";

// Mirrors app/(chat)/layout.tsx's auth check in reverse: an already
// signed-in user landing here (typed the URL directly, followed a stale
// bookmark/link, or got redirected here mid-session before Auth.js's
// cookie state settled) should never see the login form again -- send
// them straight to the app instead. Bug report, 2026-09-06: this check
// didn't exist at all, so the form rendered unconditionally regardless of
// session state.
export default async function LoginPage() {
  const session = await auth();
  if (session?.user) {
    redirect("/");
  }

  return (
    <div id="main-content" className="flex min-h-screen flex-col items-center justify-center gap-6 px-8 text-center">
      <div className="flex flex-col items-center gap-2">
        <img src="/logo-mark.png" alt="" aria-hidden className="h-12 w-12" />
        <h1 className="text-2xl font-semibold tracking-tight">Itinera</h1>
        <p className="text-muted-foreground">Sign in to plan trips and save your chat history.</p>
      </div>
      <form
        action={async () => {
          "use server";
          await signIn("google", { redirectTo: "/" });
        }}
      >
        <Button type="submit" size="lg" className="px-6">
          Continue with Google
        </Button>
      </form>
      {/* This app has no separate signup flow -- Google OAuth unifies both
          (see backend/app/auth.py: get_current_user auto-provisions a User
          row the first time it sees a new google_sub). A distinct "Sign Up"
          button here would trigger the identical action as "Log In", which
          reads as broken rather than helpful -- this line answers the same
          "am I in the right place" question new users have, honestly. */}
      <p className="max-w-xs text-sm text-muted-foreground">
        New here? Signing in with Google creates your account automatically --
        no separate sign-up needed.
      </p>
    </div>
  );
}
