import "server-only";
import { SignJWT } from "jose";

// Pure signer, no session lookup -- used both by authHeader.ts (which reads
// the current session first) and by auth.ts's jwt callback directly (which
// already has the sub/email at hand and can't easily call auth() on
// itself mid-callback). One signing implementation, not two.
//
// `provider` tells backend/app/auth.py's get_current_user how to interpret
// `sub` -- for "google" (the default, and every token minted before this
// param existed) it's Google's OIDC subject; for "credentials" it's this
// app's own internal User.id. Defaulting to "google" keeps every existing
// call site (which only ever passed sub/email) compiling and behaving
// exactly as before.
export async function mintBackendJwt(
  sub: string,
  email?: string | null,
  provider: string = "google"
): Promise<string> {
  const secret = process.env.AUTH_BACKEND_SECRET;
  if (!secret) {
    console.error("AUTH_BACKEND_SECRET is not set -- backend calls will be unauthenticated");
    throw new Error("AUTH_BACKEND_SECRET is not set");
  }

  return new SignJWT({ email: email ?? undefined, provider })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(sub)
    .setIssuedAt()
    .setExpirationTime("60s")
    .sign(new TextEncoder().encode(secret));
}
