from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, weather_service
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[schemas.ConversationSummary])
def list_conversations(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Real ownership scoping as of Phase C (see CLAUDE.md decision log,
    # "Auth" row) -- previously trusted a client-supplied `user_id` query
    # param (DEFAULT_USER_ID = 1), exactly as untrustworthy as the old
    # TripRequest.user_id field was. Always the authenticated caller's own
    # conversations now, never anyone else's by passing a different id.
    conversations = (
        db.query(models.Conversation)
        .filter(models.Conversation.user_id == user.id)
        .order_by(models.Conversation.created_at.desc())
        .all()
    )
    return conversations


@router.get("/{conversation_id}", response_model=schemas.ConversationDetail)
def get_conversation(
    conversation_id: int, user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    # Ownership check as of Phase C -- 404, not 403, on a cross-user id so
    # this doesn't even confirm the id exists to someone who doesn't own it.
    conversation = (
        db.query(models.Conversation)
        .filter(models.Conversation.id == conversation_id, models.Conversation.user_id == user.id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages_out = []
    for message in conversation.messages:
        trip_out = None
        if message.trip is not None:
            trip = message.trip
            # Same cached-read pattern as routers/trips.py -- this is what
            # actually renders long-term (the frontend reloads the whole
            # conversation after every turn), so it needs the forecast too.
            weather_out = weather_service.get_or_refresh_trip_weather(trip, trip.items)
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

    db.commit()  # persists any weather cache refreshed above

    return schemas.ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        messages=messages_out,
        tour_guide_mode=conversation.tour_guide_mode,
    )


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

    db.delete(conversation)
    db.commit()
    return {"deleted": True}
