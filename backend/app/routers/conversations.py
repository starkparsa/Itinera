from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/conversations", tags=["conversations"])

# Matches the placeholder user pattern used in trips.py -- no auth yet, so
# every conversation currently belongs to this single default user.
DEFAULT_USER_ID = 1


@router.get("", response_model=list[schemas.ConversationSummary])
def list_conversations(user_id: int = DEFAULT_USER_ID, db: Session = Depends(get_db)):
    conversations = (
        db.query(models.Conversation)
        .filter(models.Conversation.user_id == user_id)
        .order_by(models.Conversation.created_at.desc())
        .all()
    )
    return conversations


@router.get("/{conversation_id}", response_model=schemas.ConversationDetail)
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conversation = db.query(models.Conversation).filter(models.Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages_out = []
    for message in conversation.messages:
        trip_out = None
        if message.trip is not None:
            trip = message.trip
            trip_out = schemas.TripResponse(
                trip_id=trip.id,
                destination=trip.destination,
                itinerary=[schemas.ItineraryItemOut.model_validate(i) for i in trip.items],
                conversation_id=conversation.id,
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

    return schemas.ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        messages=messages_out,
    )


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conversation = db.query(models.Conversation).filter(models.Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.delete(conversation)
    db.commit()
    return {"deleted": True}
