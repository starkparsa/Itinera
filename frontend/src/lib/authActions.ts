"use server";

import { signIn, signOut } from "@/auth";

export async function signOutAction() {
  await signOut({ redirectTo: "/login" });
}

// Re-consent fallback, not the common path -- the base login (src/auth.ts)
// already requests the Calendar scope, so a normal sign-in covers this.
// This only gets called when CalendarPushButton's push attempt comes back
// "not connected" despite that (a stored credential going stale, e.g. the
// 7-day refresh-token cap Google applies to an unverified/"Testing"-status
// OAuth app, or the user manually revoking access in their Google account
// settings) -- forces a fresh consent screen (prompt: "consent") to get a
// new refresh token in that recovery case.
export async function connectGoogleCalendarAction() {
  await signIn("google", {
    redirectTo: "/",
    authorizationParams: {
      scope: "openid email profile https://www.googleapis.com/auth/calendar.events",
      access_type: "offline",
      prompt: "consent",
    },
  });
}
