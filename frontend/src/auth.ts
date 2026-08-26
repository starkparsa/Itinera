import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { mintBackendJwt } from "@/lib/mintBackendJwt";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

// Auth.js (NextAuth) is the OAuth client and session owner -- see CLAUDE.md's
// decision log ("Auth" row) for the full BFF architecture. JWT session
// strategy (not database sessions) so there's no second ORM/schema in Node
// land alongside the existing Python/SQLAlchemy models; the session lives
// entirely in Auth.js's own encrypted cookie and never reaches FastAPI.
//
// FastAPI never sees this session or talks to Google at all -- it only ever
// verifies a separate, short-lived JWT that lib/backend.ts mints server-side
// per request (see backend/app/auth.py).
export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google({
      // Calendar scope is bundled into the base login itself -- Calendar
      // push ("Export Plan") is now the app's one export path, so nearly
      // every user needs this, and asking for it as a separate step later
      // is pure friction. Deliberately NOT prompt: "consent" -- that would
      // force a full consent screen on *every* login, not just the first.
      // Google shows consent naturally on a genuinely first-ever grant
      // (exactly when we need the refresh_token, and access_type=offline
      // guarantees we get one then); a returning user's login is
      // recognized as already-consented and skips straight through. We
      // already persist that first refresh token and reuse it
      // (google_calendar.py), so there's no need for Google to reissue one
      // on every single login.
      authorization: {
        params: {
          scope: "openid email profile https://www.googleapis.com/auth/calendar.events",
          access_type: "offline",
        },
      },
    }),
  ],
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
  },
  callbacks: {
    async jwt({ token, account }) {
      // account is only present on the initial sign-in request -- persist
      // Google's stable subject id (providerAccountId) onto the token so
      // it survives every later request in this session.
      if (account) {
        token.sub = account.providerAccountId;

        // The Calendar scope above means a normal login now carries a real
        // access_token/refresh_token here too, not just the incremental
        // "Connect Google Calendar" re-consent path (still used as a rare
        // fallback -- see lib/authActions.ts -- if a stored credential ever
        // goes stale, e.g. the 7-day refresh-token cap on an unverified/
        // "Testing"-status OAuth app). Save server-side, right here, before
        // these ever touch the browser -- never passed through the session
        // cookie.
        if (account.access_token && typeof account.expires_at === "number") {
          try {
            const backendToken = await mintBackendJwt(token.sub as string, token.email as string | undefined);
            await fetch(`${BACKEND_URL}/auth/google-calendar-token`, {
              method: "POST",
              headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
              body: JSON.stringify({
                access_token: account.access_token,
                refresh_token: account.refresh_token ?? null,
                expires_at: account.expires_at,
              }),
            });
          } catch (err) {
            console.error("Failed to save Google Calendar credentials", err);
          }
        }
      }
      return token;
    },
    session({ session, token }) {
      if (token.sub) {
        session.user.sub = token.sub;
      }
      return session;
    },
  },
});
