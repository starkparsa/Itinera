from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    display_name = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

    trips = relationship("Trip", back_populates="owner", cascade="all, delete-orphan")


class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    destination = Column(String(255), nullable=False)
    prompt = Column(Text)  # the original natural-language request
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="trips")
    items = relationship("ItineraryItem", back_populates="trip", cascade="all, delete-orphan")


class ItineraryItem(Base):
    __tablename__ = "itinerary_items"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False)
    day_number = Column(Integer, nullable=False)
    time_of_day = Column(String(50))  # e.g. "morning", "14:00"
    activity = Column(Text, nullable=False)
    notes = Column(Text)

    trip = relationship("Trip", back_populates="items")
