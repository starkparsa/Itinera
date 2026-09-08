"use server";

import { signIn } from "@/auth";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

// Split out of page.tsx (a server component) so LoginCard (a client
// component, needed for the tab/toggle/toast interactivity below) can
// still trigger the real OAuth flow -- Server Actions defined in their
// own "use server" file can be imported and called directly from client
// code, same RPC mechanism as a <form action={...}>.
export async function googleSignIn() {
  await signIn("google", { redirectTo: "/" });
}

export interface EmailAuthResult {
  ok: boolean;
  error?: string;
}

// A Pydantic 422's `detail` is a list of {loc, msg, type} objects, unlike
// this app's own HTTPException calls (`detail` is a plain string, e.g.
// /auth/login's messages) -- normalize both shapes into one string so the
// caller never needs to know which validator produced the error.
function extractErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  return fallback;
}

export async function emailSignUp(email: string, password: string): Promise<EmailAuthResult> {
  try {
    const res = await fetch(`${BACKEND_URL}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, error: extractErrorMessage(body.detail, "Couldn't create your account. Try again.") };
    }
  } catch {
    return { ok: false, error: "Couldn't reach the server. Check your connection and try again." };
  }

  // Registration only creates the row (see routers/auth.py's docstring) --
  // this is the real sign-in that actually establishes a session, same
  // Credentials provider /auth/login-backed flow as emailLogin below.
  return emailLogin(email, password);
}

export async function emailLogin(email: string, password: string): Promise<EmailAuthResult> {
  // A direct pre-check, called separately from the Credentials provider's
  // own authorize() call a moment later: authorize() only gets to say
  // yes/no to signIn(), a thrown error's message doesn't reliably survive
  // that path back to the UI, so this call is what actually surfaces
  // FastAPI's specific reason (wrong password vs. "this account uses
  // Google" vs. rate-limited) to the caller.
  try {
    const res = await fetch(`${BACKEND_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const fallback = res.status === 429 ? "Too many attempts. Try again in a minute." : "Incorrect email or password.";
      return { ok: false, error: extractErrorMessage(body.detail, fallback) };
    }
  } catch {
    return { ok: false, error: "Couldn't reach the server. Check your connection and try again." };
  }

  try {
    await signIn("credentials", { email, password, redirect: false });
  } catch {
    // The pre-check above already confirmed the credentials are good --
    // reaching here means signIn()'s own plumbing failed for some other
    // reason, not a wrong password.
    return { ok: false, error: "Signed in, but couldn't start your session. Try again." };
  }
  return { ok: true };
}
