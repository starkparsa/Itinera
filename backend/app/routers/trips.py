import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from .. import (
    agent_service,
    calendar_export,
    date_resolver,
    google_calendar,
    llm_service,
    models,
    schemas,
    usage_quota,
    weather_service,
)
from ..auth import get_current_user
from ..database import get_db
from ..rate_limit import limiter

router = APIRouter(prefix="/trips", tags=["trips"])

logger = logging.getLogger(__name__)

MAX_CONTEXT_MESSAGES = 6  # how many recent turns to summarize for the LLM
MAX_CONTEXT_CHARS = 1000  # cap so long histories don't bloat every prompt
MAX_CHAT_HISTORY_MESSAGES = 10  # for the Q&A path, which uses real chat-formatted history
MAX_CHAT_MESSAGE_CHARS = 500  # per-message cap so one long turn doesn't dominate the prompt
MAX_SUMMARY_ITEMS = 10  # cap how many itinerary items get folded into the stored summary


def _build_conversation_context(conversation: models.Conversation) -> str:
    """Summarizes recent turns in a conversation into a short plain-text
    string the LLM can use as memory of what was discussed earlier. Used for
    intent classification and itinerary generation prompts.

    Builds from the MOST RECENT message backward, dropping the oldest of
    the last MAX_CONTEXT_MESSAGES turns first if the char budget is tight
    -- not a plain `[:MAX_CONTEXT_CHARS]` slice of the chronologically-
    joined string. Real bug, live-verified (2026-09-01): a user asked
    about scuba diving, got a real grounded answer (Florida Keys, Florida
    Reef Tract, Biscayne National Park), then said "can we add to the
    plan" -- the head-sliced context cut off mid-sentence through the
    scuba answer, dropping every one of those specifics, so the itinerary
    regeneration that followed had no idea what "add to the plan" was
    even asking for and produced an itinerary with zero mention of
    diving. The most recent turn is always the one a follow-up like that
    refers to, so it must never be the part that gets dropped."""
    recent = conversation.messages[-MAX_CONTEXT_MESSAGES:]
    kept: list[str] = []
    total_len = 0
    for message in reversed(recent):
        prefix = "User asked" if message.role == "user" else "Assistant"
        part = f"{prefix}: {message.content}"
        added_len = len(part) + (3 if kept else 0)  # " | " separator once joined
        if total_len + added_len > MAX_CONTEXT_CHARS:
            break
        kept.append(part)
        total_len += added_len
    return " | ".join(reversed(kept))


def _build_chat_messages(conversation: models.Conversation) -> list[dict]:
    """Real chat-formatted history (role/content pairs) for the conversational
    Q&A path, as opposed to the squashed summary string used elsewhere."""
    recent = conversation.messages[-MAX_CHAT_HISTORY_MESSAGES:]
    return [{"role": m.role, "content": m.content[:MAX_CHAT_MESSAGE_CHARS]} for m in recent]


def _summarize_itinerary(destination: str, items: list[models.ItineraryItem]) -> str:
    """Builds a compact summary of a generated itinerary to store as the
    assistant's message content -- richer than a one-line "planned a trip"
    note, so later turns in the conversation (edits, questions) have actual
    itinerary detail to reference instead of just a destination name."""
    by_day: dict[int, list[str]] = {}
    for item in items:
        by_day.setdefault(item.day_number, []).append(item.activity)

    day_lines = []
    for day_number in sorted(by_day)[:MAX_SUMMARY_ITEMS]:
        activities = ", ".join(by_day[day_number][:3])
        day_lines.append(f"Day {day_number}: {activities}")

    summary = f"Planned a {len(by_day)}-day trip to {destination}. " + "; ".join(day_lines)
    return summary[:1200]


@router.post("/generate", response_model=schemas.TripResponse)
# Stricter than the app-wide 100/minute default (see rate_limit.py) -- this
# is the one route that always makes at least one real LLM call, so it's
# the one that directly costs money per request. 10/minute per IP is
# generous for a real user's own back-and-forth planning session while
# still bounding worst-case spend from a single source. `request: Request`
# below is required by slowapi's decorator (it locates the ASGI request by
# that exact parameter name) -- distinct from `trip_request`, the actual
# request body, which is what this function used to just call `request`
# before this rate limit was added.
@limiter.limit("10/minute")
def generate_trip(
    request: Request,
    trip_request: schemas.TripRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Real auth as of Phase B (see CLAUDE.md decision log, "Auth" row) --
    # get_current_user verifies the caller's JWT and guarantees a real,
    # already-persisted User, so the old placeholder-auto-create block
    # (which trusted a client-supplied user_id) is gone. Ownership checks on
    # *other* endpoints (get_trip, calendar export, conversations) are
    # still pending -- Phase C.

    # Per-account daily cost cap, checked before anything else in this
    # function -- same "gate before anything expensive runs" discipline as
    # classify_intent below (architecture principle #1), just one step
    # earlier: a user who's already hit today's limit shouldn't cost so
    # much as a single classification call. See usage_quota.py for why this
    # is DB-backed and distinct from rate_limit.py's IP-keyed flood
    # protection.
    if not usage_quota.check_and_consume_daily_quota(user, db):
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily limit of {usage_quota.DAILY_TRIP_GENERATION_LIMIT} requests reached for "
                "this account. Try again tomorrow."
            ),
        )

    if trip_request.conversation_id:
        conversation = (
            db.query(models.Conversation)
            .filter(models.Conversation.id == trip_request.conversation_id, models.Conversation.user_id == user.id)
            .first()
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        title = trip_request.prompt[:60] + ("..." if len(trip_request.prompt) > 60 else "")
        conversation = models.Conversation(user_id=user.id, title=title)
        db.add(conversation)
        db.flush()

    conversation_context = _build_conversation_context(conversation)

    # Classify before doing anything expensive. This is what fixes messages
    # getting nonsensical itinerary-shaped replies to plain questions, and
    # is also what actually restricts the assistant to travel topics --
    # off-topic requests never reach the LLM's itinerary/agent machinery at
    # all, they get a fixed, non-LLM-generated decline.
    intent, tour_guide_requested = llm_service.classify_intent(trip_request.prompt, conversation_context)

    if intent == "off_topic":
        db.add(models.Message(conversation_id=conversation.id, role="user", content=trip_request.prompt))
        db.add(models.Message(conversation_id=conversation.id, role="assistant", content=llm_service.OFF_TOPIC_REPLY))
        db.commit()
        return schemas.TripResponse(conversation_id=conversation.id, reply=llm_service.OFF_TOPIC_REPLY)

    if intent == "question":
        chat_messages = _build_chat_messages(conversation)

        # Needed below for both the on-demand currency fetch's destination
        # hint and the real weather grounding -- looked up unconditionally
        # now (not just inside the "nothing cached yet" branch below),
        # since weather needs it on every question turn, not just the
        # first one in a conversation.
        latest_trip = (
            db.query(models.Trip)
            .filter(models.Trip.conversation_id == conversation.id)
            .order_by(models.Trip.id.desc())
            .first()
        )

        # Nothing gathered yet for this conversation at all -- try a real,
        # scoped fetch before answering rather than letting the model guess
        # (see CLAUDE.md principle #7). Gated on `is None` specifically (not
        # just falsy) so this branch's own currency gather won't re-fire on
        # every later question turn, even once it's cached "" for "found
        # nothing". Deliberately NOT the same contract itinerary generation
        # uses below (`cached_agent_context`/`was_freshly_gathered` there
        # are truthy-gated, not `is None`-gated) -- a "" cached here by a
        # Q&A turn must NOT permanently block that loop's own place-context
        # gathering; see the 2026-08-30 fix on both of those for why.
        fresh_agent_context = ""
        if conversation.agent_context is None:
            # A destination hint helps when the question itself doesn't name
            # a place ("what does the temperature look like?"); fine to
            # leave unset if no trip exists yet -- the question text alone
            # may name one, and the fetch degrades quietly either way.
            fresh_agent_context = agent_service.gather_trip_context(
                trip_request.prompt, destination=latest_trip.destination if latest_trip else None,
            )

        effective_agent_context = fresh_agent_context or (conversation.agent_context or "")

        # Real per-day forecast, if this conversation has a trip with one.
        # Regression fix: a question about weather-appropriate outfits was
        # answered with plausible-but-wrong temperatures (~70-80F for a
        # real 104-108F forecast) because this data never reached the Q&A
        # path at all -- only the currency agent_context above did (see
        # CLAUDE.md decision log). Called on every question turn, not just
        # once per conversation like the agent step above -- unlike that
        # Gemini call, weather_service caches internally (3h TTL, see
        # get_or_refresh_trip_weather), so this is a cheap cache read in
        # the common case, not a fresh fetch every time.
        weather_context = ""
        if latest_trip:
            # The generating prompt may never have named a date ("build me a
            # trip to Austin"), leaving start_date unresolved -- but the
            # question itself often does ("...this weekend"). Bug found live:
            # asking a weather question with a date phrase in the *question*
            # got "I don't have current weather data" even though the date
            # was sitting right there in the text, because this branch only
            # ever read the trip's already-resolved start_date. Try resolving
            # one from the question text too (same deterministic
            # date_resolver used at generation time -- principle #6), and
            # persist it onto the trip so this unlocks weather (and calendar
            # export) for the rest of the conversation too, not just this
            # one answer (principle #5).
            if latest_trip.start_date is None:
                resolved_start_date = date_resolver.resolve_trip_start_date(trip_request.prompt, date.today())
                if resolved_start_date:
                    latest_trip.start_date = resolved_start_date

            weather_data = weather_service.get_or_refresh_trip_weather(latest_trip, latest_trip.items)
            if weather_data:
                weather_context = weather_service.summarize_for_prompt(latest_trip.destination, weather_data)

        combined_context = " ".join(part for part in (effective_agent_context, weather_context) if part)

        # Try the place-context tool-calling loop first -- run fresh on
        # every question turn, never cached across turns (see
        # agent_service.answer_question_with_tools's docstring for why:
        # unlike the currency agent step above, a different place can be
        # asked about on every turn, so caching the first answer forever
        # would silently reuse it for every later question). It already
        # fails quietly (returns "" when QA_TOOL_CALLING_ENABLED is off or
        # on any internal error), so an empty result here just means "fall
        # back to the plain Q&A path" -- a Wikipedia/Gemini hiccup must
        # never block an answer to the user's question.
        # Captured before conversation.tour_guide_mode is mutated below --
        # true exactly on the turn that flips the mode from off to on, so
        # the deterministic acknowledgment prefix (below) fires once, on
        # activation, and never again on later turns that keep it on.
        activating_tour_guide = tour_guide_requested and not conversation.tour_guide_mode

        reply_text = agent_service.answer_question_with_tools(
            trip_request.prompt, chat_messages, agent_context=combined_context,
            # Pass the mode as it stood ENTERING this turn -- the
            # triggering "be my tour guide" turn itself already gets a
            # detailed reply via QA_TOOL_SYSTEM_PROMPT's own per-turn
            # instruction, this flag only needs to cover turns after that.
            tour_guide_mode=conversation.tour_guide_mode,
        )

        try:
            if not reply_text:
                reply_text = llm_service.answer_question(
                    trip_request.prompt, chat_messages, agent_context=combined_context,
                )
        except Exception as exc:
            logger.exception("Q&A request failed for conversation %s", conversation.id)
            raise HTTPException(status_code=502, detail=f"LLM failed to answer: {exc}")

        # Deterministic, not LLM-worded -- exact required boilerplate is
        # more reliable coming from Python than from trusting the model to
        # phrase an acknowledgment verbatim every time (principle #6's
        # discipline, extended from date arithmetic to fixed wording).
        # Applies regardless of which path above produced reply_text.
        if activating_tour_guide and not reply_text.startswith("Tour guide mode on."):
            reply_text = f"Tour guide mode on. {reply_text}"

        if conversation.agent_context is None:
            conversation.agent_context = fresh_agent_context

        # This turn explicitly asked the assistant to become a tour guide
        # -- stays on for later turns until an edit_trip/new_trip turn
        # clears it (see the branch below).
        if tour_guide_requested:
            conversation.tour_guide_mode = True

        db.add(models.Message(conversation_id=conversation.id, role="user", content=trip_request.prompt))
        db.add(models.Message(conversation_id=conversation.id, role="assistant", content=reply_text))
        db.commit()
        return schemas.TripResponse(conversation_id=conversation.id, reply=reply_text)

    # "new_trip" or "edit_trip" -- generate a full itinerary. Note: "edit_trip"
    # currently still regenerates the whole thing (with conversation_context
    # carrying the requested change) rather than surgically editing specific
    # days -- true diff-based editing is a bigger feature for another time.
    #
    # Explicitly talking about planning again turns persistent tour-guide
    # mode back off -- unconditional, regardless of tour_guide_requested
    # (INTENT_INSTRUCTIONS tells the model that combination shouldn't
    # happen, but "off" wins on a planning turn either way, so there's no
    # ambiguous state even if the model doesn't perfectly obey that).
    conversation.tour_guide_mode = False
    #
    # Looked up once here and reused for both the day-count fallback (below,
    # passed into generate_itinerary) and the start_date fallback (further
    # down) -- one query, two consumers, rather than duplicating it.
    previous_trip = (
        db.query(models.Trip)
        .filter(models.Trip.conversation_id == conversation.id)
        .order_by(models.Trip.id.desc())
        .first()
    )
    # Regression fix: a follow-up with no day-count language at all (e.g.
    # "I want to experience the artsy miami" after a real 5-day trip was
    # already generated) was silently coming back a different length,
    # because total_days was re-guessed from scratch on every call with no
    # anchor to what was already established -- see
    # llm_service._infer_trip_meta's docstring for the fix. max(day_number)
    # over the previous trip's saved items, not a second query.
    previous_total_days = None
    if previous_trip and previous_trip.items:
        previous_total_days = max(item.day_number for item in previous_trip.items)

    try:
        result = llm_service.generate_itinerary(
            trip_request.prompt,
            requested_days=trip_request.days,
            conversation_context=conversation_context,
            # Reuse currency/place-context findings gathered earlier in this
            # chat instead of re-running the agent steps on every edit turn.
            # A falsy value (None, or "" -- e.g. from a Q&A-first
            # conversation's own cache-fill, see routers/trips.py's question
            # branch) means "nothing useful cached yet, worth a fresh
            # gather" here; only a real non-empty finding is treated as
            # already-cached. (Fixed 2026-08-30 -- `is None` alone let a
            # Q&A-cached "" permanently block place-context gathering.)
            cached_agent_context=conversation.agent_context,
            previous_total_days=previous_total_days,
        )
    except Exception as exc:
        logger.exception("Itinerary generation failed for conversation %s", conversation.id)
        raise HTTPException(status_code=502, detail=f"LLM generation failed: {exc}")

    # Only surface agent findings in *this* response when they were freshly
    # gathered on this turn -- on later edit/regenerate turns the same
    # (possibly stale) findings are reused from the cache, but re-showing
    # the "Agent findings" banner every turn makes it look like the
    # assistant keeps bringing up weather/currency unprompted. See
    # CLAUDE.md architecture principle #5: cached findings should serve the
    # whole conversation, but each consumer -- including this response --
    # needs to read/surface the cache appropriately, not just blindly.
    # Truthy, not `is not None` -- matches the same fix in
    # generate_itinerary's cached_agent_context gate (llm_service.py):
    # an empty string here can come from a Q&A-first conversation's own
    # cache-fill, and treating that as "already gathered" would both skip
    # re-persisting real findings this turn just gathered *and* keep the
    # itinerary generator re-gathering from scratch on every future turn
    # instead of caching once. Found by the 2026-08-30 code review.
    was_freshly_gathered = not conversation.agent_context
    if was_freshly_gathered:
        conversation.agent_context = result.get("agent_context", "")

    # Real calendar start date, resolved in Python (never LLM arithmetic --
    # principle #6). If this turn's prompt doesn't say a date (e.g. an
    # edit_trip turn like "make it longer"), fall back to whatever the
    # previous trip in this conversation resolved (looked up once, above,
    # and reused here), the same reuse pattern already used for the
    # agent_context cache and the Q&A destination hint.
    start_date = date_resolver.resolve_trip_start_date(trip_request.prompt, date.today())
    if start_date is None and previous_trip:
        start_date = previous_trip.start_date

    trip = models.Trip(
        user_id=user.id,
        conversation_id=conversation.id,
        destination=result.get("destination", "Unknown"),
        prompt=trip_request.prompt,
        start_date=start_date,
    )
    db.add(trip)

    try:
        db.flush()  # get trip.id before inserting items/messages

        items_out = []
        for day in result.get("days", []):
            for item in day.get("items", []):
                db_item = models.ItineraryItem(
                    trip_id=trip.id,
                    day_number=day["day_number"],
                    time_of_day=item.get("time_of_day"),
                    activity=item.get("activity"),
                    notes=item.get("notes"),
                )
                db.add(db_item)
                items_out.append(db_item)

        weather_out = weather_service.get_or_refresh_trip_weather(trip, items_out)

        assistant_summary = _summarize_itinerary(trip.destination, items_out)

        db.add(models.Message(conversation_id=conversation.id, role="user", content=trip_request.prompt))
        db.add(models.Message(
            conversation_id=conversation.id, role="assistant",
            content=assistant_summary, trip_id=trip.id,
        ))

        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save trip: {exc}")

    db.refresh(trip)

    return schemas.TripResponse(
        trip_id=trip.id,
        destination=trip.destination,
        itinerary=[schemas.ItineraryItemOut.model_validate(i) for i in items_out],
        note=result.get("note"),
        agent_context=result.get("agent_context") if was_freshly_gathered else None,
        conversation_id=conversation.id,
        weather=[schemas.DayWeatherOut(**w) for w in weather_out],
        start_date=trip.start_date,
    )


@router.get("/{trip_id}", response_model=schemas.TripResponse)
def get_trip(trip_id: int, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Ownership check as of Phase C (see CLAUDE.md decision log, "Auth"
    # row) -- 404, not 403, on a cross-user id so this doesn't even confirm
    # the id exists to someone who doesn't own it.
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id, models.Trip.user_id == user.id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    weather_out = weather_service.get_or_refresh_trip_weather(trip, trip.items)
    db.commit()

    return schemas.TripResponse(
        trip_id=trip.id,
        destination=trip.destination,
        itinerary=[schemas.ItineraryItemOut.model_validate(i) for i in trip.items],
        conversation_id=trip.conversation_id,
        weather=[schemas.DayWeatherOut(**w) for w in weather_out],
        start_date=trip.start_date,
    )


@router.get("/{trip_id}/calendar.ics")
def export_trip_calendar(trip_id: int, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Downloadable .ics calendar for a trip (build-order item 3, CLAUDE.md --
    .ics only, PDF out of scope for now). This is a defensive check for
    direct API callers -- the frontend itself never surfaces an export
    button until a trip has a resolved start_date, so a real user should
    never hit the 400 below."""
    # Ownership check as of Phase C -- see get_trip above, same reasoning.
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id, models.Trip.user_id == user.id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if not trip.start_date:
        raise HTTPException(status_code=400, detail="Trip has no resolved start date; cannot export a calendar.")

    ics_bytes = calendar_export.build_trip_calendar(trip.id, trip.destination, trip.start_date, trip.items)
    filename = calendar_export.ics_filename(trip.destination)
    return Response(
        content=ics_bytes,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{trip_id}/push-to-calendar")
def push_trip_to_calendar(trip_id: int, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Pushes a trip's itinerary as real events onto the user's Google
    Calendar (build-order item 5, Phase D -- see CLAUDE.md decision log,
    "Auth" row, and google_calendar.py for why this goes through
    googleapiclient directly rather than Gemini/MCP). Same ownership check
    as the other trip endpoints (Phase C)."""
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id, models.Trip.user_id == user.id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if not trip.start_date:
        raise HTTPException(status_code=400, detail="Trip has no resolved start date; cannot push to calendar.")

    try:
        result = google_calendar.push_trip_to_calendar(db, user, trip)
    except google_calendar.CalendarNotConnectedError:
        # 428 Precondition Required -- distinct from a real failure, so the
        # frontend can prompt the user to connect Calendar access instead
        # of showing a generic error.
        raise HTTPException(status_code=428, detail="Google Calendar is not connected for this account.")
    except HttpError as exc:
        logger.exception("Calendar push failed for trip %s", trip_id)
        raise HTTPException(status_code=502, detail=f"Google Calendar API error: {exc.reason}")

    return result
