import "server-only";
import { auth } from "@/auth";
import { mintBackendJwt } from "./mintBackendJwt";

// Mints the short-lived, backend-scoped JWT FastAPI verifies (see
// backend/app/auth.py and CLAUDE.md's decision log, "Auth" row) -- shared
// between lib/backend.ts's Server Actions and the .ics-export Route
// Handler, both of which need the same header, neither of which should
// duplicate the signing logic.
export async function backendAuthHeader(): Promise<Record<string, string>> {
  const session = await auth();
  if (!session?.user?.sub) return {};

  try {
    const token = await mintBackendJwt(session.user.sub, session.user.email);
    return { Authorization: `Bearer ${token}` };
  } catch {
    return {};
  }
}
