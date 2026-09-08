import { redirect } from "next/navigation";
import { auth } from "@/auth";
import LoginCard from "@/components/login/LoginCard";
import { facebookSignIn, googleSignIn } from "./actions";

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

  return <LoginCard onGoogleSignIn={googleSignIn} onFacebookSignIn={facebookSignIn} />;
}
