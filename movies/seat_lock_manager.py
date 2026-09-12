import time
import logging
import threading
from datetime import datetime
from django.db import transaction, models
from django.db.utils import OperationalError
from django.utils import timezone
from django.db.models import Q
from .models import Show, Booking, SeatLock

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_SECONDS = 120  # 2 minutes auto timeout

_cleanup_thread = None
_cleanup_lock = threading.Lock()
_should_run = True


class SeatConflictError(Exception):
    def __init__(self, conflicting_seats, message=None):
        self.conflicting_seats = conflicting_seats
        if not message:
            seats_str = ", ".join(conflicting_seats)
            message = f"The following seat(s) are temporarily locked or already booked by another user: {seats_str}"
        super().__init__(message)


def cleanup_expired_locks():
    """Marks all locks with expires_at <= now as EXPIRED."""
    try:
        now = timezone.now()
        expired_count = SeatLock.objects.filter(
            status='LOCKED',
            expires_at__lte=now
        ).update(status='EXPIRED')
        if expired_count > 0:
            logger.info(f"Cleaned up {expired_count} expired seat locks.")
        return expired_count
    except Exception as e:
        logger.exception("Error cleaning up expired seat locks")
        return 0


def _worker_loop():
    logger.info("Starting seat lock cleanup worker loop...")
    while _should_run:
        try:
            cleanup_expired_locks()
            time.sleep(5)
        except Exception:
            logger.exception("Error in seat lock cleanup worker loop")
            time.sleep(5)
    logger.info("Seat lock cleanup worker loop stopped.")


def start_lock_cleanup_worker():
    global _cleanup_thread
    with _cleanup_lock:
        if _cleanup_thread is None or not _cleanup_thread.is_alive():
            _cleanup_thread = threading.Thread(
                target=_worker_loop,
                daemon=True,
                name="CineShowSeatLockWorker"
            )
            _cleanup_thread.start()
            logger.info("CineShow Seat Lock Worker Thread started.")


def lock_seats(show_id, seat_list, session_id, timeout_seconds=LOCK_TIMEOUT_SECONDS):
    """
    Concurrency-Safe Seat Reservation.
    Uses database row-level locking via transaction.atomic() & select_for_update() on the Show record.
    Prevents race conditions sub-millisecond across multiple users.
    """
    if not seat_list or not isinstance(seat_list, list):
        raise ValueError("seat_list must be a non-empty list of seat numbers.")
    if not session_id:
        raise ValueError("session_id is required.")

    # Normalize seat numbers (trim whitespace, uppercase)
    normalized_seats = [s.strip().upper() for s in seat_list if s.strip()]

    with transaction.atomic():
        # 1. Lock the parent Show record to serialize concurrent reservation requests for this show
        try:
            show = Show.objects.select_for_update().get(id=show_id)
        except Show.DoesNotExist:
            raise ValueError(f"Show with id {show_id} does not exist.")
        except OperationalError:
            # Concurrency lock contention: Another thread holds the database lock for this show
            raise SeatConflictError(normalized_seats, "Seats are currently being locked by another concurrent request. Please try again.")

        now = timezone.now()

        # 2. Expire old locks for this show inline
        SeatLock.objects.filter(
            show=show,
            status='LOCKED',
            expires_at__lte=now
        ).update(status='EXPIRED')

        # 3. Check for already confirmed bookings
        successful_bookings = Booking.objects.filter(
            show=show,
            status='SUCCESS'
        )
        booked_seats = set()
        for b in successful_bookings:
            for s in b.seat_numbers.split(','):
                if s.strip():
                    booked_seats.add(s.strip().upper())

        # 4. Check for active locks by other users
        active_locks = SeatLock.objects.filter(
            show=show,
            status='LOCKED',
            expires_at__gt=now
        )
        
        conflicting_seats = []
        for s in normalized_seats:
            if s in booked_seats:
                conflicting_seats.append(s)
            else:
                # Check if locked by someone else
                lock_by_other = active_locks.filter(seat_number=s).exclude(session_id=session_id).exists()
                if lock_by_other:
                    conflicting_seats.append(s)

        if conflicting_seats:
            raise SeatConflictError(conflicting_seats)

        # 5. Lock seats for current session
        expires_at = now + timezone.timedelta(seconds=timeout_seconds)

        # Clear any previous locks for these seats for this session if they were released/expired
        SeatLock.objects.filter(
            show=show,
            seat_number__in=normalized_seats,
            session_id=session_id
        ).delete()

        created_locks = []
        for s in normalized_seats:
            lock = SeatLock.objects.create(
                show=show,
                seat_number=s,
                session_id=session_id,
                expires_at=expires_at,
                status='LOCKED'
            )
            created_locks.append(lock)

        return {
            'seats': normalized_seats,
            'expires_at': expires_at.isoformat(),
            'timeout_seconds': timeout_seconds,
            'session_id': session_id,
        }


def release_seats(show_id, seat_list, session_id):
    """Releases active locks for the specified session_id."""
    if not seat_list or not session_id:
        return 0
    normalized_seats = [s.strip().upper() for s in seat_list if s.strip()]
    with transaction.atomic():
        released_count = SeatLock.objects.filter(
            show_id=show_id,
            seat_number__in=normalized_seats,
            session_id=session_id,
            status='LOCKED'
        ).update(status='RELEASED')
        return released_count


def convert_locks_to_booking(show_id, seat_list, session_id):
    """Converts active locks to CONVERTED upon successful payment."""
    normalized_seats = [s.strip().upper() for s in seat_list if s.strip()]
    with transaction.atomic():
        converted_count = SeatLock.objects.filter(
            show_id=show_id,
            seat_number__in=normalized_seats,
            session_id=session_id,
            status='LOCKED'
        ).update(status='CONVERTED')
        return converted_count


def get_seats_status(show_id, session_id=None):
    """
    Returns seat layout status for a given show.
    Default seat grid: Rows A, B, C, D with numbers 1..8 (A1..D8).
    """
    now = timezone.now()

    # Expire stale locks inline
    SeatLock.objects.filter(
        show_id=show_id,
        status='LOCKED',
        expires_at__lte=now
    ).update(status='EXPIRED')

    # Get confirmed bookings
    successful_bookings = Booking.objects.filter(
        show_id=show_id,
        status='SUCCESS'
    )
    booked_seats = set()
    for b in successful_bookings:
        for s in b.seat_numbers.split(','):
            if s.strip():
                booked_seats.add(s.strip().upper())

    # Get active locks
    active_locks = SeatLock.objects.filter(
        show_id=show_id,
        status='LOCKED',
        expires_at__gt=now
    )

    lock_map = {}
    for l in active_locks:
        rem_sec = max(0, int((l.expires_at - now).total_seconds()))
        lock_map[l.seat_number.upper()] = {
            'session_id': l.session_id,
            'expires_at': l.expires_at.isoformat(),
            'seconds_remaining': rem_sec
        }

    rows = ['A', 'B', 'C', 'D']
    cols = 8
    seats_data = []

    for r in rows:
        for c in range(1, cols + 1):
            seat_code = f"{r}{c}"
            if seat_code in booked_seats:
                state = 'booked'
                lock_info = None
            elif seat_code in lock_map:
                info = lock_map[seat_code]
                if session_id and info['session_id'] == session_id:
                    state = 'locked_by_me'
                else:
                    state = 'locked_by_other'
                lock_info = {
                    'seconds_remaining': info['seconds_remaining'],
                    'expires_at': info['expires_at']
                }
            else:
                state = 'available'
                lock_info = None

            seats_data.append({
                'seat_number': seat_code,
                'status': state,
                'lock_info': lock_info
            })

    return seats_data
