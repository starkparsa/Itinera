// @vitest-environment node
//
// jsdom's TextEncoder produces a Uint8Array from a different realm than
// Node's, and jose's webapi key-type check is a strict `instanceof
// Uint8Array` -- under jsdom that check fails even though the bytes are
// correct. This module has no DOM dependency, so run it under Node instead.
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { jwtVerify } from "jose";

// mintBackendJwt.ts is marked "server-only" (Next.js's client/server import
// guard) -- real in the app (webpack refuses to bundle it into a client
// component), but the package throws unconditionally outside that specific
// bundling context, including under Vitest. Stubbing it is the standard way
// to unit-test a server-only module directly.
vi.mock("server-only", () => ({}));
const { mintBackendJwt } = await import("./mintBackendJwt");

const SECRET = "test-only-secret-not-a-real-value";
const originalSecret = process.env.AUTH_BACKEND_SECRET;

beforeEach(() => {
  process.env.AUTH_BACKEND_SECRET = SECRET;
});

afterEach(() => {
  process.env.AUTH_BACKEND_SECRET = originalSecret;
});

// Tests the real signer backend/app/auth.py actually verifies against --
// not a mock of Google (which this app never talks to on the backend side,
// see docs/manual-auth-testing.md), so this is a legitimate small gap
// closed rather than an attempt to test Google's own consent screen.
describe("mintBackendJwt", () => {
  it("produces a JWT verifiable with the same shared secret, carrying the right subject and email", async () => {
    const token = await mintBackendJwt("google-sub-123", "jordan@example.com");

    const { payload, protectedHeader } = await jwtVerify(token, new TextEncoder().encode(SECRET));

    expect(protectedHeader.alg).toBe("HS256");
    expect(payload.sub).toBe("google-sub-123");
    expect(payload.email).toBe("jordan@example.com");
  });

  it("sets a short (~60s) expiration, matching backend/app/auth.py's short-lived-token assumption", async () => {
    const token = await mintBackendJwt("google-sub-123");
    const { payload } = await jwtVerify(token, new TextEncoder().encode(SECRET));

    const ttlSeconds = (payload.exp as number) - (payload.iat as number);
    expect(ttlSeconds).toBe(60);
  });

  it("omits the email claim entirely when none is given, rather than a placeholder value", async () => {
    const token = await mintBackendJwt("google-sub-123");
    const { payload } = await jwtVerify(token, new TextEncoder().encode(SECRET));

    expect(payload.email).toBeUndefined();
  });

  it("throws when AUTH_BACKEND_SECRET isn't configured, rather than signing with an empty key", async () => {
    delete process.env.AUTH_BACKEND_SECRET;
    await expect(mintBackendJwt("google-sub-123")).rejects.toThrow("AUTH_BACKEND_SECRET is not set");
  });

  it("defaults the provider claim to 'google' when omitted, for every pre-existing call site", async () => {
    const token = await mintBackendJwt("google-sub-123");
    const { payload } = await jwtVerify(token, new TextEncoder().encode(SECRET));
    expect(payload.provider).toBe("google");
  });

  it("carries a real 'credentials' provider claim when passed, for backend/app/auth.py's internal-id lookup", async () => {
    const token = await mintBackendJwt("42", "jordan@example.com", "credentials");
    const { payload } = await jwtVerify(token, new TextEncoder().encode(SECRET));
    expect(payload.sub).toBe("42");
    expect(payload.provider).toBe("credentials");
  });
});
