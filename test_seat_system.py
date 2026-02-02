#!/usr/bin/env python3
"""
Comprehensive Test Suite for Seat Management System
Tests all critical scenarios including concurrency, edge cases, and failure recovery
"""

import requests
import threading
import random
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import signal
import sys

BASE_URL = "http://localhost:5000"
SHOW_ID = "avengers_2026_7pm"
TEST_SHOW_ID = "test_show_123"

# Demo show has 50 seats (A1-A10, B1-B10, C1-C10, D1-D10, E1-E10)
TOTAL_SEATS = 50

# Colors for output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

lock = threading.Lock()
all_tests_passed = True

def print_header(title):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}{Colors.RESET}")

def print_success(message):
    print(f"{Colors.GREEN}✓ {message}{Colors.RESET}")

def print_failure(message):
    global all_tests_passed
    all_tests_passed = False
    print(f"{Colors.RED}✗ {message}{Colors.RESET}")

def print_info(message):
    print(f"{Colors.BLUE}ℹ {message}{Colors.RESET}")

def print_warning(message):
    print(f"{Colors.YELLOW}⚠ {message}{Colors.RESET}")

def get_seat_status(show_id=SHOW_ID):
    """Get current seat status for a show"""
    try:
        r = requests.get(f"{BASE_URL}/shows/{show_id}/seats", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print_failure(f"Failed to get seat status: {e}")
        return None

def verify_seat_invariant(show_id=SHOW_ID):
    """Verify that available + held + booked == total_seats"""
    status = get_seat_status(show_id)
    if not status:
        return False
    
    total = status["available_seats"] + status["held_seats"] + status["booked_seats"]
    invariant_ok = total == status["total_seats"]
    
    if not invariant_ok:
        print_failure(f"Seat invariant violated! {total} != {status['total_seats']}")
        print_info(f"  Available: {status['available_seats']}, Held: {status['held_seats']}, Booked: {status['booked_seats']}")
    
    return invariant_ok

def reset_show():
    """Reset the show to initial state (all seats available)"""
    print_info("Resetting show to initial state...")
    
    # Get current status
    status = get_seat_status()
    if not status:
        return False
    
    # If already reset (all available), skip
    if status["held_seats"] == 0 and status["booked_seats"] == 0:
        print_success("Show already in clean state")
        return True

    try:
        requests.post("http://127.0.0.1:5000/reset", timeout=15)
        time.sleep(1)  # Wait for reset
    except Exception as exc:
        print_warning(f"Reset endpoint call failed: {exc}")
    
    return verify_seat_invariant()

# ============================================================================
# TEST CATEGORY 1: Basic Seat State & Availability
# ============================================================================

def test_basic_booking():
    """Test basic seat booking flow"""
    print_header("TEST 1: Basic Seat Booking")
    
    # Reset show
    reset_show()
    
    # Book 2 seats
    seats_to_book = ["A1", "A2"]
    hold_resp = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": seats_to_book, "hold_duration_seconds": 60},
        timeout=15
    )
    
    if hold_resp.status_code != 201:
        print_failure(f"Failed to hold seats: {hold_resp.status_code}")
        return False
    
    hold_id = hold_resp.json()["hold_id"]
    print_success(f"Hold created: {hold_id}")
    
    # Book the held seats
    book_resp = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/book",
        json={"hold_id": hold_id},
        timeout=15
    )
    
    if book_resp.status_code != 200:
        print_failure(f"Failed to book seats: {book_resp.status_code}")
        return False
    
    print_success("Seats booked successfully")
    
    # Verify status
    status = get_seat_status()
    if status["booked_seats"] != 2:
        print_failure(f"Expected 2 booked seats, got {status['booked_seats']}")
        return False
    
    print_success("Basic booking test passed")
    return verify_seat_invariant()

def test_insufficient_seats():
    """Test that booking fails when insufficient seats available"""
    print_header("TEST 2: Insufficient Seats")
    
    reset_show()
    
    # Try to book more seats than available
    seats_to_book = [f"{row}{num}" for row in "ABCDE" for num in range(1, 11)]  # 50 valid seats  # 50 seats
    hold_resp = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": seats_to_book, "hold_duration_seconds": 60},
        timeout=15
    )
    
    if hold_resp.status_code != 201:
        print_failure(f"Failed to hold all seats: {hold_resp.status_code}")
        return False
    
    hold_id = hold_resp.json()["hold_id"]
    
    # Now try to hold one more seat (should fail)
    extra_seat_resp = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": ["B1"], "hold_duration_seconds": 60},
        timeout=15
    )
    
    if extra_seat_resp.status_code == 201:
        print_failure("Should not be able to hold seat when all are taken!")
        return False
    
    print_success("Insufficient seats test passed")
    return verify_seat_invariant()

def test_invalid_inputs():
    """Test invalid inputs are rejected"""
    print_header("TEST 3: Invalid Inputs")

    # Test 1: Empty seat list
    resp1 = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": [], "hold_duration_seconds": 60},
        timeout=15
    )
    if resp1.status_code != 400:
        print_failure(f"Empty seat list should be rejected with 400, got {resp1.status_code}")
        return False

    # Test 2: seat_ids not an array
    resp2 = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": "A1"},
        timeout=15
    )
    if resp2.status_code != 400:
        print_failure(f"Non-array seat_ids should be rejected with 400, got {resp2.status_code}")
        return False

    # Test 3: seat_ids containing non-string
    resp3 = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": ["A1", 123]},
        timeout=15
    )
    if resp3.status_code != 400:
        print_failure(f"seat_ids containing non-string should be rejected with 400, got {resp3.status_code}")
        return False

    # Test 4: hold_duration_seconds invalid type
    resp4 = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": ["A1"], "hold_duration_seconds": "fast"},
        timeout=15
    )
    if resp4.status_code != 400:
        print_failure(f"Invalid duration type should be rejected with 400, got {resp4.status_code}")
        return False

    # Test 5: Invalid show ID
    resp5 = requests.get(f"{BASE_URL}/shows/invalid_show/seats", timeout=15)
    if resp5.status_code != 404:
        print_failure(f"Invalid show should return 404, got {resp5.status_code}")
        return False

    # Test 6: Booking without hold_id
    resp6 = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/book",
        json={},
        timeout=15
    )
    if resp6.status_code != 400:
        print_failure(f"Missing hold_id should return 400, got {resp6.status_code}")
        return False

    # Test 7: Release hold with invalid payload
    resp7 = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/release-hold",
        json={"hold_id": 123},
        timeout=15
    )
    if resp7.status_code != 400:
        print_failure(f"Non-string hold_id should return 400, got {resp7.status_code}")
        return False

    print_success("Invalid inputs test passed")
    return True

# ============================================================================
# TEST CATEGORY 2: Concurrency & Race Conditions
# ============================================================================

def concurrent_booking_worker(user_id, seats_per_user, results):
    """Worker function for concurrent booking test"""
    try:
        # Pick random seats
        all_seats = [f"{row}{num}" for row in "ABCDE" for num in range(1, 11)]
        chosen_seats = random.sample(all_seats, seats_per_user)
        
        # Try to hold
        hold_resp = requests.post(
            f"{BASE_URL}/shows/{SHOW_ID}/hold",
            json={"seat_ids": chosen_seats, "hold_duration_seconds": 60},
            timeout=10
        )
        
        with lock:
            if hold_resp.status_code == 201:
                results["success"] += 1
                hold_id = hold_resp.json()["hold_id"]
                
                # Book immediately
                book_resp = requests.post(
                    f"{BASE_URL}/shows/{SHOW_ID}/book",
                    json={"hold_id": hold_id},
                    timeout=10
                )
                
                if book_resp.status_code == 200:
                    results["booked"] += 1
                else:
                    results["hold_only"] += 1
            else:
                results["failed"] += 1
                
    except Exception as e:
        with lock:
            results["failed"] += 1

def test_concurrent_bookings():
    """Test concurrent bookings don't cause overbooking"""
    print_header("TEST 4: Concurrent Bookings (Race Condition)")
    
    reset_show()
    
    num_users = 100
    seats_per_user = 1
    
    results = {"success": 0, "failed": 0, "booked": 0, "hold_only": 0}
    
    print_info(f"Starting {num_users} concurrent users, each trying to book {seats_per_user} seat...")
    
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [
            executor.submit(concurrent_booking_worker, i, seats_per_user, results)
            for i in range(num_users)
        ]
        for _ in as_completed(futures):
            pass
    
    duration = time.time() - start_time
    
    print_info(f"Test completed in {duration:.2f}s")
    print_info(f"Results: {results}")
    
    # Verify final state
    status = get_seat_status()
    
    if status["booked_seats"] > TOTAL_SEATS:
        print_failure(f"OVERBOOKING! {status['booked_seats']} seats booked out of {TOTAL_SEATS}")
        return False
    
    if status["booked_seats"] != results["booked"]:
        print_warning(f"Discrepancy: {status['booked_seats']} booked in DB, {results['booked']} reported by clients")
    
    expected_booked = min(num_users, TOTAL_SEATS)
    if status["booked_seats"] > expected_booked:
        print_failure(f"Booked {status['booked_seats']} but expected max {expected_booked}")
        return False
    
    print_success(f"Concurrent booking test passed: {status['booked_seats']} seats booked safely")
    return verify_seat_invariant()

def test_last_seat_race():
    """Test that last seat is not double-booked"""
    print_header("TEST 5: Last Seat Race Condition")
    
    reset_show()
    
    # CORRECTED: Precompute all seats to avoid duplicates
    all_seats = [f"{row}{num}" for row in "ABCDE" for num in range(1, 11)]  # ['A1','A2',...,'E10']
    last_seat = all_seats[-1]  # 'E10' - the seat we'll race for
    
    # Book first 49 seats (indices 0-48), leaving last_seat available
    for i in range(TOTAL_SEATS - 1):
        seat = all_seats[i]
        hold_resp = requests.post(
            f"{BASE_URL}/shows/{SHOW_ID}/hold",
            json={"seat_ids": [seat], "hold_duration_seconds": 60},
            timeout=15
        )
        if hold_resp.status_code != 201:
            print_failure(f"Setup failed: Could not hold seat {seat} (status {hold_resp.status_code})")
            return False
        
        book_resp = requests.post(
            f"{BASE_URL}/shows/{SHOW_ID}/book",
            json={"hold_id": hold_resp.json()["hold_id"]},
            timeout=15
        )
        if book_resp.status_code != 200:
            print_failure(f"Setup failed: Could not book seat {seat} (status {book_resp.status_code})")
            return False
    
    status = get_seat_status()
    print_info(f"Booked {status['booked_seats']} seats, {status['available_seats']} remaining (expecting 1 available: {last_seat})")
    
    # Thread-safe counter for race results
    lock = threading.Lock()
    results = {"success": 0, "failed": 0}
    
    def race_for_last_seat(user_id):
        try:
            # Attempt to hold the LAST seat (critical section)
            hold_resp = requests.post(
                f"{BASE_URL}/shows/{SHOW_ID}/hold",
                json={"seat_ids": [last_seat], "hold_duration_seconds": 60},
                timeout=10
            )
            
            if hold_resp.status_code == 201:
                hold_id = hold_resp.json()["hold_id"]
                # CRITICAL: Verify booking succeeds before counting success
                book_resp = requests.post(
                    f"{BASE_URL}/shows/{SHOW_ID}/book",
                    json={"hold_id": hold_id},
                    timeout=10
                )
                with lock:
                    if book_resp.status_code == 200:
                        results["success"] += 1
                    else:
                        results["failed"] += 1
                        logger.warning(f"User {user_id}: Hold succeeded but booking failed (status {book_resp.status_code})")
            else:
                with lock:
                    results["failed"] += 1
        except Exception as e:
            with lock:
                results["failed"] += 1
                logger.error(f"User {user_id} exception: {str(e)}")
    
    # Launch 10 concurrent requests for the last seat
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(race_for_last_seat, i) for i in range(10)]
        for _ in as_completed(futures):
            pass
    
    final_status = get_seat_status()
    
    # VALIDATION 1: System must have exactly TOTAL_SEATS booked
    if final_status["booked_seats"] != TOTAL_SEATS:
        print_failure(
            f"Seat count invariant violated! "
            f"Expected {TOTAL_SEATS} booked seats, got {final_status['booked_seats']} "
            f"(held: {final_status['held_seats']}, available: {final_status['available_seats']})"
        )
        return False
    
    # VALIDATION 2: Exactly ONE thread must have successfully BOOKED the seat
    if results["success"] != 1:
        print_failure(
            f"Race condition detected! "
            f"Expected exactly 1 successful booking, got {results['success']} successes "
            f"and {results['failed']} failures"
        )
        return False
    
    # VALIDATION 3: Verify no seat state corruption
    if not verify_seat_invariant():
        print_failure("Seat state invariant check failed after race")
        return False
    
    print_success(
        f"Last seat race condition test PASSED! "
        f"(1 success, {results['failed']} failures, {TOTAL_SEATS} seats booked)"
    )
    return True

# ============================================================================
# TEST CATEGORY 3: Seat Holding / Reservation Lifecycle
# ============================================================================

def test_hold_timeout():
    """Test that held seats are released after timeout"""
    print_header("TEST 6: Hold Timeout")
    
    reset_show()
    
    # Hold a seat with short timeout
    hold_resp = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": ["A1"], "hold_duration_seconds": 60},
        timeout=15
    )
    
    if hold_resp.status_code != 201:
        print_failure("Failed to hold seat")
        return False
    
    hold_id = hold_resp.json()["hold_id"]
    print_info(f"Hold created: {hold_id}")
    
    status = get_seat_status()
    if status["held_seats"] != 1:
        print_failure("Seat should be in held state")
        return False
    
    # Wait for timeout
    print_info("Waiting for hold timeout (72 seconds)...")
    time.sleep(72) #60 default and 10 for refresh
    
    status = get_seat_status()
    
    if status["held_seats"] != 0:
        print_failure(f"Seat should be released, but {status['held_seats']} still held")
        return False
    
    if status["available_seats"] != TOTAL_SEATS:
        print_failure(f"Seat should be available again")
        return False
    
    print_success("Hold timeout test passed")
    return verify_seat_invariant()

def test_hold_booking_before_timeout():
    """Test that booking before timeout works"""
    print_header("TEST 7: Booking Before Hold Timeout")
    
    reset_show()
    
    hold_resp = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": ["B5"], "hold_duration_seconds": 60},
        timeout=15
    )
    
    if hold_resp.status_code != 201:
        print_failure("Failed to hold seat")
        return False
    
    hold_id = hold_resp.json()["hold_id"]
    
    # Book immediately
    book_resp = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/book",
        json={"hold_id": hold_id},
        timeout=15
    )
    
    if book_resp.status_code != 200:
        print_failure("Failed to book held seat")
        return False
    
    status = get_seat_status()
    
    if status["booked_seats"] != 1:
        print_failure("Seat should be booked")
        return False
    
    if status["held_seats"] != 0:
        print_failure("No seats should be held")
        return False
    
    print_success("Booking before timeout test passed")
    return verify_seat_invariant()

def test_hold_by_different_users():
    """Test that different users can hold different seats simultaneously"""
    print_header("TEST 8: Multiple Users Holding Different Seats")
    
    reset_show()
    
    # User 1 holds seat A1
    hold1 = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": ["A1"], "hold_duration_seconds": 60},
        timeout=15
    )
    
    if hold1.status_code != 201:
        print_failure("User 1 failed to hold seat")
        return False
    
    hold_id1 = hold1.json()["hold_id"]
    
    # User 2 holds seat A2
    hold2 = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": ["A2"], "hold_duration_seconds": 60},
        timeout=15
    )
    
    if hold2.status_code != 201:
        print_failure("User 2 failed to hold seat")
        return False
    
    hold_id2 = hold2.json()["hold_id"]
    
    status = get_seat_status()
    
    if status["held_seats"] != 2:
        print_failure(f"Expected 2 held seats, got {status['held_seats']}")
        return False
    
    # Both users book their seats
    book1 = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/book",
        json={"hold_id": hold_id1},
        timeout=15
    )
    
    book2 = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/book",
        json={"hold_id": hold_id2},
        timeout=15
    )
    
    if book1.status_code != 200 or book2.status_code != 200:
        print_failure("Failed to book held seats")
        return False
    
    final_status = get_seat_status()
    
    if final_status["booked_seats"] != 2:
        print_failure(f"Expected 2 booked seats, got {final_status['booked_seats']}")
        return False
    
    print_success("Multiple users holding different seats test passed")
    return verify_seat_invariant()

# ============================================================================
# TEST CATEGORY 4: Idempotency & Duplicate Requests
# ============================================================================

def test_idempotent_booking():
    """Test that duplicate booking requests return consistent booking identity and state"""
    print_header("TEST 9: Idempotent Booking")
    
    reset_show()
    
    # Hold seat
    hold_resp = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": ["C3"], "hold_duration_seconds": 60},
        timeout=5
    )
    if hold_resp.status_code != 201:
        print_failure(f"Hold failed: {hold_resp.status_code} {hold_resp.text}")
        return False
    hold_id = hold_resp.json()["hold_id"]
    
    # Send 3 identical booking requests (simulate client retries)
    responses = []
    for i in range(3):
        resp = requests.post(
            f"{BASE_URL}/shows/{SHOW_ID}/book",
            json={"hold_id": hold_id},
            timeout=5
        )
        responses.append(resp)
    
    # ✅ VALIDATE 1: All requests succeed (idempotency contract)
    for i, resp in enumerate(responses):
        if resp.status_code != 200:
            print_failure(f"Request #{i+1} failed: {resp.status_code} {resp.text}")
            return False
    
    # ✅ VALIDATE 2: CRITICAL FIELDS MATCH EXACTLY (booking identity)
    # booking_id and seat_ids MUST be identical - this is the core idempotency guarantee
    booking_ids = []
    seat_id_sets = []
    
    for i, resp in enumerate(responses):
        try:
            data = resp.json()
            if "booking_id" not in data or "seat_ids" not in data:
                print_failure(f"Response #{i+1} missing required fields: {data}")
                return False
            
            booking_ids.append(data["booking_id"])
            seat_id_sets.append(tuple(sorted(data["seat_ids"])))  # Normalize for comparison
            
        except Exception as e:
            print_failure(f"Invalid JSON in response #{i+1}: {e} | Raw: {resp.text}")
            return False
    
    # Verify all booking IDs are identical
    if len(set(booking_ids)) != 1:
        print_failure(f"Inconsistent booking IDs across requests: {booking_ids}")
        return False
    
    # Verify all seat selections are identical
    if len(set(seat_id_sets)) != 1:
        print_failure(f"Inconsistent seat selections across requests: {seat_id_sets}")
        return False
    
    # ✅ VALIDATE 3: System state integrity (NO double-booking)
    status = get_seat_status()
    if status["booked_seats"] != 1:
        print_failure(f"Expected exactly 1 booked seat, found {status['booked_seats']}")
        return False
    
    # ✅ VALIDATE 4: Specific seat state verification
    seat_c3 = next((s for s in status["seats"] if s["seat_id"] == "C3"), None)
    if not seat_c3 or seat_c3["status"] != "booked":
        print_failure(f"Seat C3 invalid state: {seat_c3}")
        return False
    
    # ✅ VALIDATE 5: Booking ID matches hold ID (implementation-specific check)
    if booking_ids[0] != hold_id:
        print_warning(
            f"Booking ID ({booking_ids[0]}) != Hold ID ({hold_id}). "
            "Acceptable if design generates new IDs, but verify intent."
        )
    
    # ✅ VALIDATE 6: Optional timestamp sanity check (non-blocking)
    # Subsequent responses should return identical timestamps (from DB)
    if len(responses) > 1:
        try:
            ts_second = responses[1].json().get("booked_at")
            ts_third = responses[2].json().get("booked_at")
            if ts_second and ts_third and ts_second != ts_third:
                print_warning(
                    f"Non-identical timestamps in retry responses (may indicate race): "
                    f"Resp2={ts_second}, Resp3={ts_third}"
                )
        except:
            pass  # Non-critical
    
    print_success(
        f"Idempotent booking verified: "
        f"Consistent booking ID ({booking_ids[0]}), "
        f"1 seat booked, "
        f"all requests succeeded"
    )
    return verify_seat_invariant()

# ============================================================================
# TEST CATEGORY 5: Edge Cases & Boundary Conditions
# ============================================================================

def test_boundary_conditions():
    """Test edge cases like 0 seats, negative seats, etc."""
    print_header("TEST 10: Boundary Conditions")
    
    reset_show()
    
    # Test 1: Try to hold 0 seats
    resp1 = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": [], "hold_duration_seconds": 60},
        timeout=15
    )
    if resp1.status_code not in [400, 409]:
        print_failure(f"Empty seat list should be rejected, got {resp1.status_code}")
        return False
    
    # Test 2: Try to hold all seats at once
    all_seats = [f"{row}{num}" for row in "ABCDE" for num in range(1, 11)]
    resp2 = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/hold",
        json={"seat_ids": all_seats, "hold_duration_seconds": 60},
        timeout=15
    )
    if resp2.status_code != 201:
        print_failure(f"Should be able to hold all {len(all_seats)} seats")
        return False
    
    hold_id = resp2.json()["hold_id"]
    
    # Book all seats
    book_resp = requests.post(
        f"{BASE_URL}/shows/{SHOW_ID}/book",
        json={"hold_id": hold_id},
        timeout=15
    )
    if book_resp.status_code != 200:
        print_failure("Failed to book all seats")
        return False
    
    status = get_seat_status()
    
    if status["booked_seats"] != TOTAL_SEATS:
        print_failure(f"Expected {TOTAL_SEATS} booked, got {status['booked_seats']}")
        return False
    
    if status["available_seats"] != 0:
        print_failure("No seats should be available")
        return False
    
    print_success("Boundary conditions test passed")
    return verify_seat_invariant()

# ============================================================================
# TEST CATEGORY 6: State Consistency & Invariants
# ============================================================================

def test_seat_invariants():
    """Test that seat state invariants always hold"""
    print_header("TEST 11: Seat State Invariants")
    
    reset_show()
    
    # Perform a series of operations
    operations = [
        ("hold", ["A1", "A2"], 60),
        ("book", None, None),
        ("hold", ["B1"], 60),
        ("hold", ["B2"], 60),
        ("book", None, None),
        ("book", None, None),
    ]
    
    hold_ids = []
    
    for i, (op, seats, duration) in enumerate(operations):
        try:
            if op == "hold":
                resp = requests.post(
                    f"{BASE_URL}/shows/{SHOW_ID}/hold",
                    json={"seat_ids": seats, "hold_duration_seconds": duration},
                    timeout=15
                )
                if resp.status_code == 201:
                    hold_ids.append(resp.json()["hold_id"])
            elif op == "book":
                if hold_ids:
                    hold_id = hold_ids.pop(0)
                    requests.post(
                        f"{BASE_URL}/shows/{SHOW_ID}/book",
                        json={"hold_id": hold_id},
                        timeout=15
                    )
            
            # Check invariant after each operation
            if not verify_seat_invariant():
                print_failure(f"Invariant violated after operation {i}")
                return False
                
        except Exception as e:
            print_failure(f"Operation {i} failed: {e}")
            return False
    
    print_success("Seat invariants test passed")
    return True

# ============================================================================
# TEST CATEGORY 7: Comprehensive Stress Test
# ============================================================================

def comprehensive_stress_test():
    """Comprehensive stress test combining all scenarios"""
    print_header("TEST 12: Comprehensive Stress Test")
    
    reset_show()
    
    TOTAL_USERS = 200
    SEATS_PER_USER = 2
    BOOK_PROBABILITY = 0.6
    
    all_seats = [f"{row}{num}" for row in "ABCDE" for num in range(1, 11)]
    
    results = {
        "hold_success": 0,
        "hold_failed": 0,
        "book_success": 0,
        "book_failed": 0,
        "abandoned": 0,
    }
    
    def user_flow(user_id):
        chosen_seats = random.sample(all_seats, SEATS_PER_USER)
        
        try:
            hold_resp = requests.post(
                f"{BASE_URL}/shows/{SHOW_ID}/hold",
                json={
                    "seat_ids": chosen_seats,
                    "hold_duration_seconds": random.randint(60, 180)
                },
                timeout=10
            )
            
            if hold_resp.status_code != 201:
                with lock:
                    results["hold_failed"] += 1
                return
            
            hold_data = hold_resp.json()
            hold_id = hold_data["hold_id"]
            
            with lock:
                results["hold_success"] += 1
            
            time.sleep(random.uniform(0.1, 1.5))
            
            if random.random() < BOOK_PROBABILITY:
                book_resp = requests.post(
                    f"{BASE_URL}/shows/{SHOW_ID}/book",
                    json={"hold_id": hold_id},
                    timeout=10
                )
                
                if book_resp.status_code == 200:
                    with lock:
                        results["book_success"] += 1
                else:
                    with lock:
                        results["book_failed"] += 1
            else:
                with lock:
                    results["abandoned"] += 1
                    
        except Exception as e:
            with lock:
                results["hold_failed"] += 1
    
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(user_flow, i) for i in range(TOTAL_USERS)]
        for _ in as_completed(futures):
            pass
    
    duration = time.time() - start_time
    
    print_info(f"Stress test completed in {duration:.2f}s")
    for k, v in results.items():
        print_info(f"  {k:15}: {v}")
    
    # Verify final state
    status = get_seat_status()
    
    total = status["available_seats"] + status["held_seats"] + status["booked_seats"]
    
    print_info(f"\nFinal seat counts:")
    print_info(f"  Available: {status['available_seats']}")
    print_info(f"  Held: {status['held_seats']}")
    print_info(f"  Booked: {status['booked_seats']}")
    print_info(f"  Total: {total}/{status['total_seats']}")
    
    if total != status["total_seats"]:
        print_failure("Seat count mismatch!")
        return False
    
    if status["booked_seats"] > status["total_seats"]:
        print_failure("OVERBOOKING DETECTED!")
        return False
    
    print_success("Comprehensive stress test passed")
    return True

# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

def run_all_tests():
    """Run all test categories"""
    print_header("SEAT MANAGEMENT SYSTEM - COMPREHENSIVE TEST SUITE")
    print_info(f"Base URL: {BASE_URL}")
    print_info(f"Show ID: {SHOW_ID}")
    print_info(f"Total Seats: {TOTAL_SEATS}\n")
    
    tests = [
        ("Basic Booking", test_basic_booking),
        ("Insufficient Seats", test_insufficient_seats),
        ("Invalid Inputs", test_invalid_inputs),
        ("Concurrent Bookings", test_concurrent_bookings),
        ("Last Seat Race", test_last_seat_race),
        ("Hold Timeout", test_hold_timeout),
        ("Booking Before Timeout", test_hold_booking_before_timeout),
        ("Multiple Users Holding", test_hold_by_different_users),
        ("Idempotent Booking", test_idempotent_booking),
        ("Boundary Conditions", test_boundary_conditions),
        ("Seat Invariants", test_seat_invariants),
        ("Comprehensive Stress", comprehensive_stress_test),
    ]
    
    results = []
    
    for i, (name, test_func) in enumerate(tests, 1):
        print(f"\n{Colors.BOLD}Test {i}/{len(tests)}: {name}{Colors.RESET}")
        print("-" * 60)
        
        try:
            start = time.time()
            passed = test_func()
            duration = time.time() - start
            
            results.append({
                "name": name,
                "passed": passed,
                "duration": duration
            })
            
            if passed:
                print_success(f"✓ {name} passed ({duration:.2f}s)")
            else:
                print_failure(f"✗ {name} failed ({duration:.2f}s)")
                
        except Exception as e:
            print_failure(f"✗ {name} crashed: {e}")
            results.append({"name": name, "passed": False, "duration": 0})
        
        # Small delay between tests
        time.sleep(1)
    
    # Print summary
    print_header("TEST SUMMARY")
    
    passed_count = sum(1 for r in results if r["passed"])
    failed_count = len(results) - passed_count
    
    print(f"\n{Colors.BOLD}Total Tests: {len(results)}{Colors.RESET}")
    print(f"{Colors.GREEN}Passed: {passed_count}{Colors.RESET}")
    print(f"{Colors.RED}Failed: {failed_count}{Colors.RESET}\n")
    
    print("Detailed Results:")
    for r in results:
        status = f"{Colors.GREEN}✓{Colors.RESET}" if r["passed"] else f"{Colors.RED}✗{Colors.RESET}"
        print(f"  {status} {r['name']:30} ({r['duration']:.2f}s)")
    
    if all_tests_passed:
        print(f"\n{Colors.GREEN}{Colors.BOLD}🎉 ALL TESTS PASSED!{Colors.RESET}\n")
        return 0
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}❌ SOME TESTS FAILED{Colors.RESET}\n")
        return 1

def signal_handler(sig, frame):
    print(f"\n{Colors.YELLOW}⚠ Test interrupted by user{Colors.RESET}")
    sys.exit(1)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    exit_code = run_all_tests()
    sys.exit(exit_code)
