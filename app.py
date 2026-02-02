"""HTTP entrypoint for the seat management backend."""

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import logging
import threading
import time
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
import signal
import atexit
from typing import Any, Dict, List, Optional, Tuple

load_dotenv()
from database_manager import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Instantiate the database layer once so all request handlers reuse the same pool
DATABASE_URL = os.getenv('DATABASE_URL')
db = DatabaseManager(DATABASE_URL)


def bad_request(message: str, *, details: Optional[Dict[str, Any]] = None):
    """Return a uniform 400 payload, optionally including field-level details."""
    payload: Dict[str, Any] = {"error": message}
    if details:
        payload["details"] = details
    return jsonify(payload), 400


def require_json_object() -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[str, int]]]:
    """Ensure the request body is a JSON object before proceeding."""
    if not request.is_json:
        return None, bad_request("request body must be a JSON object")

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, bad_request("request body must be a JSON object")

    return data, None


def validate_seat_ids(seat_ids: Any) -> Tuple[Optional[List[str]], Optional[Tuple[str, int]]]:
    """Validate seat identifiers and return a deduplicated list."""
    if not isinstance(seat_ids, list):
        return None, bad_request("seat_ids must be provided as a non-empty JSON array")

    if len(seat_ids) == 0:
        return None, bad_request("seat_ids must contain at least one seat")

    normalized: List[str] = []
    for index, seat in enumerate(seat_ids):
        if not isinstance(seat, str):
            return None, bad_request("each seat_id must be a string", details={"index": index})
        trimmed = seat.strip()
        if not trimmed:
            return None, bad_request("seat_ids must not contain empty strings", details={"index": index})
        normalized.append(trimmed)

    if len(set(normalized)) != len(normalized):
        return None, bad_request("seat_ids must not contain duplicates")

    return normalized, None

def initialize_demo_show():
    """Create an example show so local demos have usable data."""
    demo_show_id = "avengers_2026_7pm"
    demo_seats = [f"{row}{num}" for row in "ABCDE" for num in range(1, 11)]
    
    try:
        success, message = db.initialize_show(demo_show_id, demo_seats)
        if success:
            logger.info(f"✅ Pre-initialized demo show: {demo_show_id}")
        else:
            logger.info(f"ℹ️ Demo show already exists: {demo_show_id}")
    except Exception as e:
        logger.error(f"❌ Failed to initialize demo show: {e}")

# Initialize demo show on module load (works with Gunicorn)
initialize_demo_show()



active_cleanup = True

def background_cleanup():
    """Periodically remove expired holds without blocking the request thread."""
    thread_db = DatabaseManager(os.getenv('DATABASE_URL'))  # Thread-local DB connection
    while active_cleanup:
        try:
            cleaned = thread_db.cleanup_expired_holds()
            if cleaned > 0:
                logger.info(f"Background cleanup: {cleaned} holds released")
        except Exception as e:
            logger.error(f"Background cleanup error: {e}")
        time.sleep(10)

    # Ensure DB connection is closed when thread stops
    try:
        thread_db.engine.dispose()
        logger.info("Cleanup thread terminated gracefully and DB connection closed.")
    except Exception as e:
        logger.error(f"Error closing DB connection: {e}")

# Kick off cleanup in a dedicated daemon so it never blocks HTTP traffic
cleanup_thread = threading.Thread(target=background_cleanup, daemon=True)
cleanup_thread.start()
def stop_background_cleanup(*args):
    """Signal handler to terminate the cleaner gracefully."""
    global active_cleanup
    if active_cleanup:
        active_cleanup = False
        logger.info("Stopping background cleanup thread...")

# Register signal handlers for production (Gunicorn, Docker, etc.)
signal.signal(signal.SIGTERM, stop_background_cleanup)
signal.signal(signal.SIGINT, stop_background_cleanup)

# Fallback for local runs (e.g., python app.py)
atexit.register(stop_background_cleanup)

# API Endpoints

@app.route("/")
def home_page():
    """Serve a minimal landing page for manual inspection."""
    return render_template("home.html")

@app.route('/shows/<show_id>/initialize', methods=['POST'])
def initialize_show(show_id):
    """Create a new show with the provided seat map."""
    data, error_response = require_json_object()
    if error_response:
        return error_response

    seat_ids_raw = data.get('seat_ids')
    seat_ids, seat_error = validate_seat_ids(seat_ids_raw)
    if seat_error:
        return seat_error

    success, message = db.initialize_show(show_id, seat_ids)
    
    if success:
        logger.info(f"Initialized show {show_id} with {len(seat_ids)} seats")
        return jsonify({
            "message": message,
            "show_id": show_id,
            "seat_count": len(seat_ids)
        }), 201
    else:
        return jsonify({"error": message}), 409

@app.route('/shows/<show_id>/seats', methods=['GET'])
def get_seat_status(show_id):
    """Return the live seat summary for a show."""
    status = db.get_seat_status(show_id)
    if status is None:
        return jsonify({"error": "show not found"}), 404
    
    return jsonify(status)

@app.route('/shows/<show_id>/hold', methods=['POST'])
def hold_seats(show_id):
    """Place a temporary hold on the requested seats."""
    data, error_response = require_json_object()
    if error_response:
        return error_response

    seat_ids_raw = data.get('seat_ids')
    seat_ids, seat_error = validate_seat_ids(seat_ids_raw)
    if seat_error:
        return seat_error

    duration_raw = data.get('hold_duration_seconds', 60)
    if isinstance(duration_raw, bool):  # Reject boolean masquerading as int
        return bad_request("hold_duration_seconds must be an integer between 60 and 1800 seconds")

    if isinstance(duration_raw, (int, float)):
        duration_int = int(duration_raw)
    elif isinstance(duration_raw, str) and duration_raw.isdigit():
        duration_int = int(duration_raw)
    else:
        if 'hold_duration_seconds' in data:
            return bad_request("hold_duration_seconds must be an integer between 60 and 1800 seconds")
        duration_int = 60

    duration = max(60, min(duration_int, 1800))

    success, result = db.hold_seats(show_id, seat_ids, duration)
    
    if success:
        logger.info(f"Hold created: {show_id}, hold_id={result['hold_id']}")
        return jsonify(result), 201
    else:
        return jsonify(result), 409 if "unavailable" in result.get("error", "") else 400

@app.route('/shows/<show_id>/book', methods=['POST'])
def book_seats(show_id):
    """Convert an active hold into a confirmed booking."""
    data, error_response = require_json_object()
    if error_response:
        return error_response

    hold_id = data.get('hold_id')
    if not isinstance(hold_id, str) or not hold_id.strip():
        return bad_request("hold_id must be a non-empty string")
    hold_id = hold_id.strip()
    
    success, result = db.book_hold(show_id, hold_id)
    
    if success:
        logger.info(f"Booking confirmed: {show_id}, booking_id={result['booking_id']}")
        return jsonify(result), 200
    else:
        return jsonify(result), 400

@app.route('/shows/<show_id>/release-hold', methods=['POST'])
def release_hold(show_id):
    """Release a hold early, making seats available immediately."""
    data, error_response = require_json_object()
    if error_response:
        return error_response

    hold_id = data.get('hold_id')
    if not isinstance(hold_id, str) or not hold_id.strip():
        return bad_request("hold_id must be a non-empty string")

    if db.release_hold(show_id, hold_id.strip()):
        logger.info(f"Hold released: {show_id}, hold_id={hold_id}")
        return jsonify({"message": "hold released"}), 200
    else:
        return jsonify({"error": "hold not found"}), 404

@app.route('/reset', methods=['POST'])
def reset_all_shows():
    """Administrative endpoint to reset the entire dataset."""
    # Optional: allow an empty JSON body for future extensibility while validating if provided
    if request.data:
        data, error_response = require_json_object()
        if error_response:
            return error_response
        if data:
            return bad_request("reset payload must be empty")

    success, result = db.reset_all_seats()

    if success:
        logger.info(
            "System reset: %s holds cleared, %s bookings cleared, %s seats reset",
            result.get('holds_cleared', 0),
            result.get('bookings_cleared', 0),
            result.get('seats_reset', 0)
        )
        response = {"message": "all shows reset", **result}
        return jsonify(response), 200

    logger.error(f"System reset failed: {result.get('error')}")
    return jsonify({"error": "reset failed", "details": result.get('error')}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Expose the database connectivity and show count."""
    return jsonify(db.health_check())


if __name__ == '__main__':
    # Pre-initialize demo show
    demo_show_id = "avengers_2026_7pm"
    demo_seats = [f"{row}{num}" for row in "ABCDE" for num in range(1, 11)]
    
    success, message = db.initialize_show(demo_show_id, demo_seats)
    if success:
        logger.info(f"Pre-initialized demo show: {demo_show_id}")
    
    logger.info("""
    ================================
    SEAT MANAGEMENT SYSTEM (POSTGRES)
    ================================
    Demo show: avengers_2026_7pm (50 seats)
    Database: PostgreSQL
    Concurrency: Row-level locking with SELECT FOR UPDATE
    ================================
    """)
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
