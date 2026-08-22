from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import llm_service, models, schemas
from ..database import get_db

router = APIRouter(prefix="/trips", tags=["trips"])

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
def generate_trip(request: schemas.TripRequest, db: Session = Depends(get_db)):
    # No auth system yet -- ensure the placeholder user this request points
    # at actually exists, otherwise inserts below fail their foreign key
    # constraint. Once real auth is added, this block goes away.
    user = db.query(models.User).filter(models.User.id == request.user_id).first()
    if not user:
        user = models.User(id=request.user_id, email=f"placeholder-{request.user_id}@example.com")
        db.add(user)
        db.flush()

    if request.conversation_id:
        conversation = (
            db.query(models.Conversation)
            .filter(models.Conversation.id == request.conversation_id, models.Conversation.user_id == request.user_id)
            .first()
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        title = request.prompt[:60] + ("..." if len(request.prompt) > 60 else "")
        conversation = models.Conversation(user_id=request.user_id, title=title)
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
        try:
            reply_text = llm_service.answer_question(request.prompt, chat_messages)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM failed to answer: {exc}")

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
            request.prompt, requested_days=request.days, conversation_context=conversation_context,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM generation failed: {exc}")

    trip = models.Trip(
        user_id=request.user_id,
        conversation_id=conversation.id,
        destination=result.get("destination", "Unknown"),
        prompt=request.prompt,
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
        agent_context=result.get("agent_context"),
        conversation_id=conversation.id,
    )


@router.get("/{trip_id}", response_model=schemas.TripResponse)
def get_trip(trip_id: int, db: Session = Depends(get_db)):
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    return schemas.TripResponse(
        trip_id=trip.id,
        destination=trip.destination,
        itinerary=[schemas.ItineraryItemOut.model_validate(i) for i in trip.items],
        conversation_id=trip.conversation_id,
    )
