import "server-only";
import { SignJWT } from "jose";

// Pure signer, no session lookup -- used both by authHeader.ts (which reads
// the current session first) and by auth.ts's jwt callback directly (which
// already has the sub/email at hand and can't easily call auth() on
// itself mid-callback). One signing implementation, not two.
export async function mintBackendJwt(sub: string, email?: string | null): Promise<string> {
  const secret = process.env.AUTH_BACKEND_SECRET;
  if (!secret) {
    console.error("AUTH_BACKEND_SECRET is not set -- backend calls will be unauthenticated");
    throw new Error("AUTH_BACKEND_SECRET is not set");
  }

  return new SignJWT({ email: email ?? undefined })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(sub)
    .setIssuedAt()
    .setExpirationTime("60s")
    .sign(new TextEncoder().encode(secret));
}
