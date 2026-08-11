from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import llm_service, models, schemas
from ..database import get_db

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("/generate", response_model=schemas.TripResponse)
def generate_trip(request: schemas.TripRequest, db: Session = Depends(get_db)):
    try:
        result = llm_service.generate_itinerary(request.prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM generation failed: {exc}")

    trip = models.Trip(
        user_id=request.user_id,
        destination=result.get("destination", "Unknown"),
        prompt=request.prompt,
    )
    db.add(trip)
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
    db.refresh(trip)

    return schemas.TripResponse(
        trip_id=trip.id,
        destination=trip.destination,
        itinerary=[schemas.ItineraryItemOut.model_validate(i) for i in items_out],
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
