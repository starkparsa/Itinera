from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas, weather_service
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/conversations", tags=["conversations"])

# Hard cap on how many conversations a single list_conversations call can
# return -- previously unbounded (see CLAUDE.md's 2026-08-31 architecture
# review), which would eventually mean loading a user's entire chat history
# into memory and over the wire on every sidebar load, no matter how long
# they've used the app. 100 is generous enough to be invisible for any
# current real user (nobody has anywhere near that many conversations yet)
# while still guaranteeing the query can never scale unbounded; a real
# "load more" UI is a separate, later frontend change once someone actually
# needs it -- `limit`/`offset` are exposed now so that can be added without
# another backend change.
DEFAULT_CONVERSATION_LIST_LIMIT = 100
MAX_CONVERSATION_LIST_LIMIT = 200


@router.get("", response_model=list[schemas.ConversationSummary])
def list_conversations(
    limit: int = Query(default=DEFAULT_CONVERSATION_LIST_LIMIT, ge=1, le=MAX_CONVERSATION_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Real ownership scoping as of Phase C (see CLAUDE.md decision log,
    # "Auth" row) -- previously trusted a client-supplied `user_id` query
    # param (DEFAULT_USER_ID = 1), exactly as untrustworthy as the old
    # TripRequest.user_id field was. Always the authenticated caller's own
    # conversations now, never anyone else's by passing a different id.
    conversations = (
        db.query(models.Conversation)
        .filter(models.Conversation.user_id == user.id)
        .order_by(models.Conversation.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    # Latest Trip id per conversation, same "max(Trip.id) grouped by
    # conversation_id" shape as routers/trips.py's list_trips -- reused
    # here rather than re-derived, so the two stay in sync automatically.
    # Scoped to just this page's conversation ids, not every trip the user
    # has ever generated.
    conversation_ids = [c.id for c in conversations]
    latest_trip_by_conversation: dict[int, int] = dict(
        db.query(models.Trip.conversation_id, func.max(models.Trip.id))
        .filter(models.Trip.user_id == user.id, models.Trip.conversation_id.in_(conversation_ids))
        .group_by(models.Trip.conversation_id)
        .all()
        if conversation_ids
        else []
    )

    return [
        schemas.ConversationSummary(
            id=c.id,
            title=c.title,
            created_at=c.created_at,
            trip_id=latest_trip_by_conversation.get(c.id),
        )
        for c in conversations
    ]


@router.get("/{conversation_id}", response_model=schemas.ConversationDetail)
def get_conversation(
    conversation_id: int, user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    # Ownership check as of Phase C -- 404, not 403, on a cross-user id so
    # this doesn't even confirm the id exists to someone who doesn't own it.
    # selectinload the whole messages -> trip -> items chain in a few
    # batched queries instead of the N+1 pattern the plain lazy-loaded
    # relationships used to produce here (one query per message's `.trip`,
    # one more per trip's `.items`) -- found in the 2026-08-31 architecture
    # review. Scales with message/trip count either way, but as a small
    # constant number of queries instead of one per row.
    conversation = (
        db.query(models.Conversation)
        .options(
            selectinload(models.Conversation.messages)
            .selectinload(models.Message.trip)
            .selectinload(models.Trip.items)
        )
        .filter(models.Conversation.id == conversation_id, models.Conversation.user_id == user.id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Only the most recently generated trip in this conversation needs a
    # freshness check (and, on a cache miss, a live geocode + forecast
    # call) on every reload -- older trips (one per earlier edit turn) just
    # serve whatever's already cached. Previously every trip with a message
    # got the full get_or_refresh_trip_weather treatment on every single
    # conversation reload, so a conversation with N edits did N freshness
    # checks (and up to N live weather fetches) for one page view, scaling
    # with edit count for no benefit -- nobody reloading a chat needs
    # "is the forecast for three edits ago still accurate". See
    # weather_service.read_cached_weather's docstring.
    latest_trip_id = max((m.trip_id for m in conversation.messages if m.trip_id), default=None)

    messages_out = []
    for message in conversation.messages:
        trip_out = None
        if message.trip is not None:
            trip = message.trip
            weather_out = (
                weather_service.get_or_refresh_trip_weather(trip, trip.items)
                if trip.id == latest_trip_id
                else weather_service.read_cached_weather(trip)
            )
            trip_out = schemas.TripResponse(
                trip_id=trip.id,
                destination=trip.destination,
                itinerary=[schemas.ItineraryItemOut.model_validate(i) for i in trip.items],
                conversation_id=conversation.id,
                weather=[schemas.DayWeatherOut(**w) for w in weather_out],
                start_date=trip.start_date,
            )
        messages_out.append(
            schemas.MessageOut(
                id=message.id,
                role=message.role,
                content=message.content,
                trip=trip_out,
                created_at=message.created_at,
            )
        )

    db.commit()  # persists the latest trip's weather cache if it was just refreshed above

    return schemas.ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        messages=messages_out,
        tour_guide_mode=conversation.tour_guide_mode,
    )


def purge_conversation(db: Session, conversation: models.Conversation) -> None:
    """Deletes a conversation and everything it produced -- explicit
    product decision, 2026-09-09, reversing the original "orphaned trip
    survives" design (see models.py's Trip.conversation_id comment and
    routers/trips.py's list_trips docstring for that original reasoning,
    and decisions.md for why it changed). Does NOT commit -- callers own
    the transaction (delete_conversation below commits once for a single
    chat; routers/auth.py's delete_account commits once after purging
    every conversation, not once per conversation).

    Messages are deleted first, not left to Conversation's own cascade
    (`messages` relationship, cascade="all, delete-orphan") -- some of
    them reference a trip via Message.trip_id (that FK has no ON DELETE
    clause), so a Trip can't be deleted while a message still points at
    it. Deleting each Trip via the ORM (not a bulk query) lets its own
    existing cascades (items/saved_places, cascade="all, delete-orphan")
    clean those up in turn -- no separate code needed for either.
    """
    for message in conversation.messages:
        db.delete(message)
    trips = db.query(models.Trip).filter(models.Trip.conversation_id == conversation.id).all()
    for trip in trips:
        db.delete(trip)
    db.delete(conversation)


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: int, user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    # Ownership check as of Phase C -- see get_conversation above, same
    # reasoning.
    conversation = (
        db.query(models.Conversation)
        .filter(models.Conversation.id == conversation_id, models.Conversation.user_id == user.id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    purge_conversation(db, conversation)
    db.commit()
    return {"deleted": True}
