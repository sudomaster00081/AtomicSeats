"""ORM model definitions describing the seat management schema."""

from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
import uuid

Base = declarative_base()

class SeatStatus(str, enum.Enum):
    """Enumerated seat lifecycle states persisted in the database."""
    AVAILABLE = 'available'
    HELD = 'held'
    BOOKED = 'booked'

class Show(Base):
    __tablename__ = 'shows'

    show_id = Column(String, primary_key=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    seats = relationship('Seat', back_populates='show', cascade='all, delete-orphan')
    holds = relationship('Hold', back_populates='show', cascade='all, delete-orphan')
    bookings = relationship('Booking', back_populates='show', cascade='all, delete-orphan')

class Seat(Base):
    __tablename__ = 'seats'
    
    show_id = Column(String, ForeignKey('shows.show_id', ondelete='CASCADE'), primary_key=True)
    seat_id = Column(String, primary_key=True)

    status = Column(Enum(SeatStatus, name='seat_status_enum', create_type=True), 
                   default=SeatStatus.AVAILABLE, nullable=False)
    hold_id = Column(UUID(as_uuid=True))
    hold_expires_at = Column(DateTime(timezone=True))
    
    show = relationship('Show', back_populates='seats')
    
    __table_args__ = (
        # REMOVED: Redundant CheckConstraint (ENUM already enforces validity)
        Index('idx_seats_status', 'status'),
        Index('idx_seats_hold_expires', 'hold_expires_at', postgresql_where=status == SeatStatus.HELD),
    )

class Hold(Base):
    __tablename__ = 'holds'
    
    hold_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    show_id = Column(String, ForeignKey('shows.show_id', ondelete='CASCADE'), nullable=False)
    seat_ids = Column(ARRAY(String), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    show = relationship('Show', back_populates='holds')
    
    __table_args__ = (
        Index('idx_holds_expires', 'expires_at'),
        Index('idx_holds_show', 'show_id'),
    )

class Booking(Base):
    __tablename__ = 'bookings'
    
    booking_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    show_id = Column(String, ForeignKey('shows.show_id', ondelete='CASCADE'), nullable=False)
    seat_ids = Column(ARRAY(String), nullable=False)
    booked_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    show = relationship('Show', back_populates='bookings')
    
    __table_args__ = (
        Index('idx_bookings_show', 'show_id'),
    )
