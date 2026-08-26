import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
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
    weather_service,
)
from ..auth import get_current_user
from ..database import get_db

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
    intent classification and itinerary generation prompts."""
    recent = conversation.messages[-MAX_CONTEXT_MESSAGES:]
    parts = []
    for message in recent:
        prefix = "User asked" if message.role == "user" else "Assistant"
        parts.append(f"{prefix}: {message.content}")
    return " | ".join(parts)[:MAX_CONTEXT_CHARS]


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
def generate_trip(
    request: schemas.TripRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Real auth as of Phase B (see CLAUDE.md decision log, "Auth" row) --
    # get_current_user verifies the caller's JWT and guarantees a real,
    # already-persisted User, so the old placeholder-auto-create block
    # (which trusted a client-supplied user_id) is gone. Ownership checks on
    # *other* endpoints (get_trip, calendar export, conversations) are
    # still pending -- Phase C.
    if request.conversation_id:
        conversation = (
            db.query(models.Conversation)
            .filter(models.Conversation.id == request.conversation_id, models.Conversation.user_id == user.id)
            .first()
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        title = request.prompt[:60] + ("..." if len(request.prompt) > 60 else "")
        conversation = models.Conversation(user_id=user.id, title=title)
        db.add(conversation)
        db.flush()

    conversation_context = _build_conversation_context(conversation)

    # Classify before doing anything expensive. This is what fixes messages
    # getting nonsensical itinerary-shaped replies to plain questions, and
    # is also what actually restricts the assistant to travel topics --
    # off-topic requests never reach the LLM's itinerary/agent machinery at
    # all, they get a fixed, non-LLM-generated decline.
    intent = llm_service.classify_intent(request.prompt, conversation_context)

    if intent == "off_topic":
        db.add(models.Message(conversation_id=conversation.id, role="user", content=request.prompt))
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
        # just falsy) so this matches the exact same cache-once-per-
        # conversation contract used for itinerary generation below
        # (`was_freshly_gathered`) -- once attempted, even "" for "found
        # nothing", it won't fire again on every later question.
        fresh_agent_context = ""
        if conversation.agent_context is None:
            # A destination hint helps when the question itself doesn't name
            # a place ("what does the temperature look like?"); fine to
            # leave unset if no trip exists yet -- the question text alone
            # may name one, and the fetch degrades quietly either way.
            fresh_agent_context = agent_service.gather_trip_context(
                request.prompt, destination=latest_trip.destination if latest_trip else None,
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
                resolved_start_date = date_resolver.resolve_trip_start_date(request.prompt, date.today())
                if resolved_start_date:
                    latest_trip.start_date = resolved_start_date

            weather_data = weather_service.get_or_refresh_trip_weather(latest_trip, latest_trip.items)
            if weather_data:
                weather_context = weather_service.summarize_for_prompt(latest_trip.destination, weather_data)

        combined_context = " ".join(part for part in (effective_agent_context, weather_context) if part)

        try:
            reply_text = llm_service.answer_question(
                request.prompt, chat_messages, agent_context=combined_context,
            )
        except Exception as exc:
            logger.exception("Q&A request failed for conversation %s", conversation.id)
            raise HTTPException(status_code=502, detail=f"LLM failed to answer: {exc}")

        if conversation.agent_context is None:
            conversation.agent_context = fresh_agent_context

        db.add(models.Message(conversation_id=conversation.id, role="user", content=request.prompt))
        db.add(models.Message(conversation_id=conversation.id, role="assistant", content=reply_text))
        db.commit()
        return schemas.TripResponse(conversation_id=conversation.id, reply=reply_text)

    # "new_trip" or "edit_trip" -- generate a full itinerary. Note: "edit_trip"
    # currently still regenerates the whole thing (with conversation_context
    # carrying the requested change) rather than surgically editing specific
    # days -- true diff-based editing is a bigger feature for another time.
    try:
        result = llm_service.generate_itinerary(
            request.prompt,
            requested_days=request.days,
            conversation_context=conversation_context,
            # Reuse weather/currency findings gathered earlier in this chat
            # instead of re-running the agent step on every edit turn.
            # conversation.agent_context is None only for a chat that hasn't
            # generated a trip yet; once set (even to "" for "found
            # nothing"), it's cached for the conversation's lifetime.
            cached_agent_context=conversation.agent_context,
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
    was_freshly_gathered = conversation.agent_context is None
    if was_freshly_gathered:
        conversation.agent_context = result.get("agent_context", "")

    # Real calendar start date, resolved in Python (never LLM arithmetic --
    # principle #6). If this turn's prompt doesn't say a date (e.g. an
    # edit_trip turn like "make it longer"), fall back to whatever the
    # previous trip in this conversation resolved, the same reuse pattern
    # already used for the agent_context cache and the Q&A destination hint.
    start_date = date_resolver.resolve_trip_start_date(request.prompt, date.today())
    if start_date is None:
        previous_trip = (
            db.query(models.Trip)
            .filter(models.Trip.conversation_id == conversation.id)
            .order_by(models.Trip.id.desc())
            .first()
        )
        if previous_trip:
            start_date = previous_trip.start_date

    trip = models.Trip(
        user_id=user.id,
        conversation_id=conversation.id,
        destination=result.get("destination", "Unknown"),
        prompt=request.prompt,
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

        db.add(models.Message(conversation_id=conversation.id, role="user", content=request.prompt))
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
