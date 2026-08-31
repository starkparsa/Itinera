"""Application-level rate limiting (slowapi -- a FastAPI/Starlette wrapper
around the `limits` library). Fixes a real gap flagged in
docs/security-review.md: with zero rate limiting, any caller (an attacker,
a compromised/leaked bearer token, or just a buggy client) could flood the
API -- and flooding /trips/generate specifically burns real Gemini/Groq
spend on every single request, since that route always makes at least one
LLM call. For a product (not a side project), an unbounded cost surface
like that is a real business risk, not just hygiene.

Keyed by remote IP (get_remote_address), not by the caller's JWT --
Next.js mints a brand-new, uniquely-timestamped bearer token on every
single backend call (see frontend/src/lib/authHeader.ts/mintBackendJwt.ts),
so the token string itself is never stable enough to bucket by. Keying by
the token's claims instead would require decoding it *before*
authentication runs (this limiter sits ahead of get_current_user), which
means trusting an unverified claim -- a forged/garbage token could pick an
always-fresh bucket for itself, letting a flood dodge the limit entirely
right up until get_current_user finally rejects each request with a 401.
Remote IP is the sturdy, unforgeable key available pre-auth.

This is deliberately NOT a per-user cost quota. A real per-account cap
(tied to the verified User.id, likely DB- or Redis-backed with a daily/
monthly ceiling) is the right longer-term mechanism to hard-cap what one
paying-or-not account can spend -- that's a product decision (what should
the cap be, does it vary by plan) as much as an engineering one, and is a
natural follow-up once there are real accounts to define it against. This
IP-based layer is the first, immediately-necessary defense against floods
and drive-by cost-bombing, not a replacement for that.

In-process/in-memory storage, not Redis -- correct and effective for a
single backend instance (today's deployment target, see
docs/deployment-guide.md's Cloud Run setup). It is NOT shared across
replicas if the backend is ever scaled horizontally: each instance
enforces its own independent counters, so the *effective* fleet-wide limit
becomes (configured limit x replica count), and a client whose requests
happen to land on different instances could exceed the intended limit.
Fine as the first real layer; point `storage_uri` at a Redis instance
(slowapi/`limits` supports this natively, no other code changes needed)
once the backend actually runs as more than one instance.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Generous global default, applied to every route automatically via
# SlowAPIMiddleware (see main.py) -- catches basic floods/credential-
# stuffing attempts against any endpoint without getting in the way of
# normal use (a real user's browser session generates nowhere near this
# many calls per minute). Routes that need a tighter limit (e.g.
# /trips/generate, the one that costs real LLM spend per call) get their
# own stricter @limiter.limit(...) decorator, which overrides this default
# for that route rather than stacking with it.
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
