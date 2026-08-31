"""Per-account daily quota on POST /trips/generate -- the real per-user cost
control flagged as a follow-up in rate_limit.py's docstring. That module's
slowapi limiter is IP-keyed flood/abuse protection: it bounds how fast
requests can arrive, not how much one *account* can cost over a day, and a
shared IP (NAT, office network) or a single account rotating IPs isn't
meaningfully capped by it. This is the other half: a hard per-User daily
ceiling on the one endpoint that always makes at least one real Gemini/Groq
call (classify_intent runs first for every single request, regardless of
intent -- new_trip, edit_trip, question, or off_topic all pay for it).

DB-backed (User.daily_request_count / daily_request_count_date), not
in-memory -- deliberately different from rate_limit.py's limiter. A cost
cap needs to hold even if the backend is ever horizontally scaled (an
in-memory-per-instance counter would let a user get (limit x replica
count) effective quota by getting routed to different instances), and it
needs to survive a restart/redeploy, which an in-memory counter wouldn't.
Reusing the existing Postgres connection costs one extra query per request
-- cheap relative to the LLM call it's gating.

Checked and consumed at the very top of generate_trip, before
classify_intent or any other LLM work runs -- the same "gate before
anything expensive runs" discipline CLAUDE.md's architecture principle #1
already applies to intent classification, just one step earlier: a user
over quota shouldn't cost so much as a single classification call.

DAILY_TRIP_GENERATION_LIMIT is a plain env var, not a per-plan/tier system
-- there's no pricing/plan model yet (see CLAUDE.md's Tier 0 LLM-provider-
dependency item), so one flat number for every account is the right amount
of complexity today. Revisit as a real per-plan quota once there's more
than one plan to differentiate.
"""
import os
from datetime import date

from sqlalchemy.orm import Session

from . import models

DAILY_TRIP_GENERATION_LIMIT = int(os.getenv("DAILY_TRIP_GENERATION_LIMIT", "20"))


def check_and_consume_daily_quota(user: "models.User", db: Session) -> bool:
    """Returns True and atomically consumes one unit of today's quota if
    the user has room left; returns False (consuming nothing) if they've
    already hit DAILY_TRIP_GENERATION_LIMIT today.

    Resets the counter itself on first use of a new calendar day, rather
    than requiring a separate cron/scheduled reset job -- the counter is
    only ever meaningful relative to `daily_request_count_date`, so a
    request on a new day naturally starts a fresh count.

    Commits immediately (not left for the caller's own end-of-request
    commit) so the consumed unit is durable even if the request goes on to
    fail for an unrelated reason (a Gemini error, a DB error saving the
    trip) -- a cost-control counter should reflect "this was attempted",
    not just "this fully succeeded", since the expensive part (the LLM
    call this gates) already happened by the time any of that could fail.
    """
    today = date.today()
    if user.daily_request_count_date != today:
        user.daily_request_count = 0
        user.daily_request_count_date = today

    if user.daily_request_count >= DAILY_TRIP_GENERATION_LIMIT:
        return False

    user.daily_request_count += 1
    db.commit()
    return True
