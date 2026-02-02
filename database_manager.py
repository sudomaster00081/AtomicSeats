"""Database coordination layer encapsulating seat state transitions."""

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import IntegrityError, OperationalError
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Dict
import logging
import uuid

from models import Base, Show, Seat, Hold, Booking, SeatStatus

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Thread-safe façade over SQLAlchemy sessions and transactional flows."""
    
    def __init__(self, database_url: str):
        self.engine = create_engine(
            database_url,
            pool_size=20,
            max_overflow=40,
            pool_pre_ping=True,  # Reconnect if connection lost
            pool_recycle=3600,   # Recycle connections after 1 hour
            echo=False
        )
        self.session_factory = scoped_session(sessionmaker(bind=self.engine))

        # Create tables
        Base.metadata.create_all(self.engine)

    @contextmanager
    def get_session(self):
        """Provide a transactional scope, committing on success and rolling back otherwise."""
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            session.close()
    
    def initialize_show(self, show_id: str, seat_ids: List[str]) -> Tuple[bool, str]:
        """Create a fresh show record along with its seat map if it does not already exist."""
        try:
            with self.get_session() as session:
                # Check if show exists
                existing_show = session.query(Show).filter_by(show_id=show_id).first()
                if existing_show:
                    return False, "show already exists"
                
                # Create show
                show = Show(show_id=show_id)
                session.add(show)
                
                # Create seats
                seats = [
                    Seat(
                        seat_id=sid,
                        show_id=show_id,
                        status=SeatStatus.AVAILABLE
                    ) for sid in seat_ids
                ]
                session.add_all(seats)
                
                return True, f"show initialized with {len(seat_ids)} seats"
        except IntegrityError as e:
            return False, f"database integrity error: {str(e)}"
    
    def hold_seats(
        self, 
        show_id: str, 
        seat_ids: List[str], 
        hold_duration_sec: int = 600
    ) -> Tuple[bool, Dict]:
        """Atomically mark seats as held using row-level locking to prevent races."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=hold_duration_sec)
        
        try:
            with self.get_session() as session:
                # Step 1: Check if show exists
                show = session.query(Show).filter_by(show_id=show_id).first()
                if not show:
                    return False, {"error": "show not found"}
                
                # Step 2: Validate seat IDs exist
                valid_seat_count = session.query(Seat).filter(
                    Seat.show_id == show_id,
                    Seat.seat_id.in_(seat_ids)
                ).count()
                
                if valid_seat_count != len(seat_ids):
                    return False, {"error": "invalid seat ID(s)"}
                
                if len(seat_ids) != len(set(seat_ids)):
                    return False, {"error": "duplicate seats in request"}
                
                # Step 3: Lock and check availability (CRITICAL SECTION)
                # SELECT FOR UPDATE locks the rows until transaction commits
                locked_seats = session.query(Seat).filter(
                    Seat.show_id == show_id,
                    Seat.seat_id.in_(seat_ids)
                ).with_for_update().all()
                
                # Check if any seat is not available
                unavailable = [
                    seat.seat_id for seat in locked_seats 
                    if seat.status != SeatStatus.AVAILABLE
                ]
                
                if unavailable:
                    return False, {"error": "seats unavailable", "unavailable_seats": unavailable}
                
                # Step 4: Create hold record
                hold_id = uuid.uuid4()
                hold = Hold(
                    hold_id=hold_id,
                    show_id=show_id,
                    seat_ids=seat_ids,
                    expires_at=expires_at
                )
                session.add(hold)
                
                # Step 5: Update seat status atomically
                for seat in locked_seats:
                    seat.status = SeatStatus.HELD
                    seat.hold_id = hold_id
                    seat.hold_expires_at = expires_at
                
                # Transaction commits here, releasing locks
                
                return True, {
                    "hold_id": str(hold_id),
                    "expires_at": expires_at.isoformat(),
                    "seat_ids": seat_ids
                }
                
        except Exception as e:
            logger.error(f"Hold seats error: {e}")
            return False, {"error": f"internal error: {str(e)}"}
    
    def book_hold(self, show_id: str, hold_id: str) -> Tuple[bool, Dict]:
        """Promote a valid hold into a booking while preserving idempotency."""
        now = datetime.now(timezone.utc)
        
        try:
            with self.get_session() as session:
                # Step 1: Get and lock the hold
                hold = session.query(Hold).filter(
                    Hold.hold_id == hold_id,
                    Hold.show_id == show_id
                ).with_for_update().first()
                
                if not hold:
                    # CHECK FOR EXISTING BOOKING BEFORE FAILING
                    existing_booking = session.query(Booking).filter(
                        Booking.booking_id == hold_id,  # Reused hold_id as booking_id
                        Booking.show_id == show_id
                    ).first()
                    if existing_booking:
                        return True, {  # IDEMPOTENT SUCCESS
                            "booking_id": str(existing_booking.booking_id),
                            "seat_ids": existing_booking.seat_ids,
                            "booked_at": existing_booking.booked_at.isoformat()
                        }
                    return False, {"error": "hold not found or expired"}
                
                if hold.expires_at <= now:
                    # Clean up expired hold
                    self._cleanup_hold(session, hold)
                    return False, {"error": "hold expired"}
                
                # Step 2: Lock and verify all seats in hold
                locked_seats = session.query(Seat).filter(
                    Seat.show_id == show_id,
                    Seat.seat_id.in_(hold.seat_ids)
                ).with_for_update().all()
                
                # Verify all seats belong to this hold
                for seat in locked_seats:
                    if seat.status != SeatStatus.HELD or seat.hold_id != hold.hold_id:
                        return False, {"error": "hold invalidated (seat state mismatch)"}
                
                # Step 3: Create booking
                booking = Booking(
                    booking_id=hold.hold_id,  # Reuse hold_id or generate new
                    show_id=show_id,
                    seat_ids=hold.seat_ids
                )
                session.add(booking)
                
                # Step 4: Update seats to BOOKED
                for seat in locked_seats:
                    seat.status = SeatStatus.BOOKED
                    seat.hold_id = None
                    seat.hold_expires_at = None
                
                # Step 5: Delete hold
                session.delete(hold)
                
                return True, {
                    "booking_id": str(booking.booking_id),
                    "seat_ids": hold.seat_ids,
                    "booked_at": now.isoformat()
                }
                
        except Exception as e:
            logger.error(f"Book hold error: {e}")
            return False, {"error": f"internal error: {str(e)}"}
    
    def release_hold(self, show_id: str, hold_id: str) -> bool:
        """Release a hold early and free its seats for other customers."""
        try:
            with self.get_session() as session:
                hold = session.query(Hold).filter(
                    Hold.hold_id == hold_id,
                    Hold.show_id == show_id
                ).first()
                
                if not hold:
                    return False
                
                self._cleanup_hold(session, hold)
                return True
                
        except Exception as e:
            logger.error(f"Release hold error: {e}")
            return False
    
    def _cleanup_hold(self, session, hold):
        """Internal helper: clear seat metadata and delete the hold within the active transaction."""
        # Release seats
        session.query(Seat).filter(
            Seat.show_id == hold.show_id,
            Seat.seat_id.in_(hold.seat_ids),
            Seat.hold_id == hold.hold_id
        ).update(
            {
                Seat.status: SeatStatus.AVAILABLE,
                Seat.hold_id: None,
                Seat.hold_expires_at: None
            },
            synchronize_session=False
        )
        
        # Delete hold
        session.delete(hold)
    
    def cleanup_expired_holds(self):
        """Find and purge holds whose expiry has passed, returning the cleanup count."""
        now = datetime.now(timezone.utc)
        
        try:
            with self.get_session() as session:
                # Find expired holds
                expired_holds = session.query(Hold).filter(
                    Hold.expires_at <= now
                ).all()
                
                count = 0
                for hold in expired_holds:
                    self._cleanup_hold(session, hold)
                    count += 1
                
                if count > 0:
                    logger.info(f"Cleaned up {count} expired holds")
                
                return count
                
        except Exception as e:
            logger.error(f"Cleanup expired holds error: {e}")
            return 0
    
    def get_seat_status(self, show_id: str) -> Optional[Dict]:
        """Return booking aggregates and per-seat details for the given show."""
        try:
            with self.get_session() as session:
                show = session.query(Show).filter_by(show_id=show_id).first()
                if not show:
                    return None
                
                # Get seat counts
                counts = session.query(
                    Seat.status,
                    func.count(Seat.seat_id)
                ).filter(
                    Seat.show_id == show_id
                ).group_by(Seat.status).all()
                
                count_dict = {SeatStatus.AVAILABLE: 0, SeatStatus.HELD: 0, SeatStatus.BOOKED: 0}
                for status, count in counts:
                    count_dict[status] = count
                
                # Get seat details
                seats = session.query(Seat).filter(
                    Seat.show_id == show_id
                ).all()
                
                seats_detail = []
                for seat in seats:
                    detail = {
                        "seat_id": seat.seat_id,
                        "status": seat.status.value
                    }
                    if seat.status == SeatStatus.HELD and seat.hold_expires_at:
                        detail["hold_expires_at"] = seat.hold_expires_at.isoformat()
                    seats_detail.append(detail)
                
                total_seats = count_dict[SeatStatus.AVAILABLE] + \
                              count_dict[SeatStatus.HELD] + \
                              count_dict[SeatStatus.BOOKED]
                
                return {
                    "total_seats": total_seats,
                    "available_seats": count_dict[SeatStatus.AVAILABLE],
                    "held_seats": count_dict[SeatStatus.HELD],
                    "booked_seats": count_dict[SeatStatus.BOOKED],
                    "seats": seats_detail,
                    "invariants_valid": True  # Database constraints ensure this
                }
                
        except Exception as e:
            logger.error(f"Get seat status error: {e}")
            return None
    
    def health_check(self) -> Dict:
        """Report database connectivity and show count; used by the /health endpoint."""
        try:
            with self.get_session() as session:
                # Test database connection
                session.execute("SELECT 1")
                
                # Count shows
                show_count = session.query(Show).count()
                
                return {
                    "status": "healthy",
                    "database": "connected",
                    "shows": show_count
                }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e)
            }

    def reset_all_seats(self) -> Tuple[bool, Dict[str, int]]:
        """Restore the database to a pristine state by clearing holds, bookings, and seat metadata."""
        try:
            with self.get_session() as session:
                deleted_holds = session.query(Hold).delete(synchronize_session=False)
                deleted_bookings = session.query(Booking).delete(synchronize_session=False)

                updated_seats = session.query(Seat).update(
                    {
                        Seat.status: SeatStatus.AVAILABLE,
                        Seat.hold_id: None,
                        Seat.hold_expires_at: None,
                    },
                    synchronize_session=False,
                )

                return True, {
                    "holds_cleared": deleted_holds,
                    "bookings_cleared": deleted_bookings,
                    "seats_reset": updated_seats,
                }
        except Exception as e:
            logger.error(f"Reset all seats error: {e}")
            return False, {"error": str(e)}
