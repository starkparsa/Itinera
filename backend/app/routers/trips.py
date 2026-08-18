from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import llm_service, models, schemas
from ..database import get_db

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("/generate", response_model=schemas.TripResponse)
def generate_trip(request: schemas.TripRequest, db: Session = Depends(get_db)):
    # No auth system yet -- ensure the placeholder user this request points
    # at actually exists, otherwise the trip insert below fails its foreign
    # key constraint. Once real auth is added, this block goes away.
    user = db.query(models.User).filter(models.User.id == request.user_id).first()
    if not user:
        user = models.User(id=request.user_id, email=f"placeholder-{request.user_id}@example.com")
        db.add(user)
        db.flush()

    try:
        result = llm_service.generate_itinerary(request.prompt, requested_days=request.days)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM generation failed: {exc}")

    trip = models.Trip(
        user_id=request.user_id,
        destination=result.get("destination", "Unknown"),
        prompt=request.prompt,
    )
    db.add(trip)

    try:
        db.flush()  # get trip.id before inserting items

        items_out = []
        for day in result.get("days", []):
            for item in day.get("items", []):
                db_item = models.ItineraryItem(
                    trip_id=trip.id,
                    day_number=day["day_number"],
                    time_of_day=item.get("time_of_day"),
                    activity=item["activity"],
                    notes=item.get("notes"),
                )
                db.add(db_item)
                items_out.append(db_item)

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
    )
