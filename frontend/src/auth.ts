import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import Facebook from "next-auth/providers/facebook";
import Credentials from "next-auth/providers/credentials";
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
    // Facebook OAuth (login page redesign Phase 2, 2026-09-07 -- see
    // decisions.md). Auth.js is the OAuth client here exactly as it is for
    // Google -- FastAPI never talks to Facebook, it only ever verifies the
    // same short-lived backend JWT (now carrying provider: "facebook") via
    // backend/app/auth.py's generalized get_current_user. No Calendar-style
    // scope needed, so unlike Google this needs no extra `authorization`
    // params -- Facebook's default `public_profile,email` scope is enough
    // to get the id/email this app actually uses.
    Facebook({
      clientId: process.env.AUTH_FACEBOOK_ID,
      clientSecret: process.env.AUTH_FACEBOOK_SECRET,
    }),
    // Email/password (login page redesign, 2026-09-07 -- see decisions.md's
    // Login page redesign entry). FastAPI owns the actual account
    // (password_hash column, bcrypt via backend/app/password_auth.py) and
    // is the only thing that ever verifies a password -- this provider is
    // a thin bridge that calls the real backend endpoint and, on success,
    // lets Auth.js mint the exact same kind of session Google already
    // gets. No parallel session/token system, per that same decision.
    Credentials({
      credentials: { email: {}, password: {} },
      authorize: async (creds) => {
        const email = creds?.email as string | undefined;
        const password = creds?.password as string | undefined;
        if (!email || !password) return null;

        const res = await fetch(`${BACKEND_URL}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        // A specific reason (invalid credentials vs. "use Google instead")
        // is surfaced to the UI by login/actions.ts's own direct call to
        // this same endpoint, made just before this one -- authorize()
        // itself only needs a yes/no here, since a thrown error's message
        // doesn't reliably survive signIn()'s own error handling.
        if (!res.ok) return null;

        const user = await res.json(); // schemas.UserAuthOut: {id, email}
        return { id: String(user.id), email: user.email };
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
      // the stable subject id (providerAccountId) onto the token so it
      // survives every later request in this session. Its *meaning*
      // depends on provider: Google's own OIDC subject for "google", or
      // this app's internal User.id (as a string, set by authorize() just
      // above) for "credentials" -- see mintBackendJwt.ts and
      // backend/app/auth.py for how each is interpreted downstream.
      if (account) {
        token.sub = account.providerAccountId;
        token.provider = account.provider;

        // Calendar push is a Google-specific feature -- explicitly gated
        // on the provider, not just on access_token/expires_at happening
        // to be present, now that a second (and soon third) provider
        // shares this same callback.
        if (account.provider === "google" && account.access_token && typeof account.expires_at === "number") {
          try {
            const backendToken = await mintBackendJwt(token.sub as string, token.email as string | undefined, "google");
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
      if (typeof token.provider === "string") {
        session.user.provider = token.provider;
      }
      return session;
    },
  },
});
