# app.py
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import logging
import threading
import time
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
load_dotenv()


from database_manager import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Initialize database
# DATABASE_URL = "postgresql://user:password@localhost:5432/seat_management"
DATABASE_URL = os.getenv('DATABASE_URL')
# Or from environment: os.getenv('DATABASE_URL')

db = DatabaseManager(DATABASE_URL)

# Background cleanup thread
active_cleanup = True

def background_cleanup():
    """Periodically clean up expired holds"""
    # CRITICAL: Create thread-local DB connection to avoid connection leaks
    thread_db = DatabaseManager(os.getenv('DATABASE_URL'))  # New isolated connection
    while active_cleanup:
        try:
            cleaned = thread_db.cleanup_expired_holds()
            if cleaned > 0:
                logger.info(f"Background cleanup: {cleaned} holds released")
            else: 
                print("cleanup with zero seats")
        except Exception as e:
            logger.error(f"Background cleanup error: {e}")
        time.sleep(10)  # Sleep AFTER processing to avoid tight loops on error

cleanup_thread = threading.Thread(target=background_cleanup, daemon=True)
cleanup_thread.start()

# API Endpoints

@app.route("/")
def home_page():

    return render_template("home.html")

@app.route('/shows/<show_id>/initialize', methods=['POST'])
def initialize_show(show_id):
    data = request.get_json()
    seat_ids = data.get('seat_ids')
    
    if not seat_ids or not isinstance(seat_ids, list):
        return jsonify({"error": "seat_ids (non-empty list) required"}), 400
    
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
    status = db.get_seat_status(show_id)
    if status is None:
        return jsonify({"error": "show not found"}), 404
    
    return jsonify(status)

@app.route('/shows/<show_id>/hold', methods=['POST'])
def hold_seats(show_id):
    data = request.get_json()
    seat_ids = data.get('seat_ids', [])
    duration = data.get('hold_duration_seconds', 600)
    
    duration = max(60, min(duration, 1800))
    
    success, result = db.hold_seats(show_id, seat_ids, duration)
    
    if success:
        logger.info(f"Hold created: {show_id}, hold_id={result['hold_id']}")
        return jsonify(result), 201
    else:
        return jsonify(result), 409 if "unavailable" in result.get("error", "") else 400

@app.route('/shows/<show_id>/book', methods=['POST'])
def book_seats(show_id):
    data = request.get_json()
    hold_id = data.get('hold_id')
    
    if not hold_id:
        return jsonify({"error": "hold_id required"}), 400
    
    success, result = db.book_hold(show_id, hold_id)
    
    if success:
        logger.info(f"Booking confirmed: {show_id}, booking_id={result['booking_id']}")
        return jsonify(result), 200
    else:
        return jsonify(result), 400

@app.route('/shows/<show_id>/release-hold', methods=['POST'])
def release_hold(show_id):
    data = request.get_json()
    hold_id = data.get('hold_id')
    
    if not hold_id:
        return jsonify({"error": "hold_id required"}), 400
    
    if db.release_hold(show_id, hold_id):
        logger.info(f"Hold released: {show_id}, hold_id={hold_id}")
        return jsonify({"message": "hold released"}), 200
    else:
        return jsonify({"error": "hold not found"}), 404

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify(db.health_check())

@app.teardown_appcontext
def shutdown_cleanup(exception=None):
    global active_cleanup
    active_cleanup = False

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
