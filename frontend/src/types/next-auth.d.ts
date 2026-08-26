import type { DefaultSession } from "next-auth";

// Auth.js's default Session.user has no `sub` field -- we add it in the
// `session` callback (see ../auth.ts) so server-side code (lib/backend.ts's
// JWT minting) can read the stable Google subject id without an `any` cast.
declare module "next-auth" {
  interface Session {
    user: {
      sub: string;
    } & DefaultSession["user"];
  }
}
