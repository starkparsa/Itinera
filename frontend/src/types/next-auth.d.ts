import type { DefaultSession } from "next-auth";

// Auth.js's default Session.user has no `sub`/`provider` fields -- we add
// them in the `session` callback (see ../auth.ts) so server-side code
// (lib/backend.ts's JWT minting) can read the stable subject id and which
// auth method produced it without an `any` cast. `sub` means different
// things per provider (Google's OIDC subject vs. this app's own internal
// User.id for "credentials") -- see mintBackendJwt.ts and
// backend/app/auth.py for how each is interpreted.
declare module "next-auth" {
  interface Session {
    user: {
      sub: string;
      provider: string;
    } & DefaultSession["user"];
  }
}
