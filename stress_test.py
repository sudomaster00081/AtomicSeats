import requests
import threading
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "http://localhost:5000"
SHOW_ID = "avengers_2026_7pm"

TOTAL_USERS = 200        # concurrent users
SEATS_PER_USER = 2
BOOK_PROBABILITY = 0.6   # 60% of users try to book, rest abandon
MAX_RETRIES = 2

all_seats = [f"{row}{num}" for row in "ABCDE" for num in range(1, 11)]
lock = threading.Lock()

results = {
    "hold_success": 0,
    "hold_failed": 0,
    "book_success": 0,
    "book_failed": 0,
    "abandoned": 0,
}

def get_seat_status():
    r = requests.get(f"{BASE_URL}/shows/{SHOW_ID}/seats")
    r.raise_for_status()
    return r.json()

def user_flow(user_id):
    """
    Simulates a single user:
    1. Picks random seats
    2. Tries to hold
    3. Randomly books or abandons
    """
    chosen_seats = random.sample(all_seats, SEATS_PER_USER)

    for attempt in range(MAX_RETRIES):
        try:
            hold_resp = requests.post(
                f"{BASE_URL}/shows/{SHOW_ID}/hold",
                json={
                    "seat_ids": chosen_seats,
                    "hold_duration_seconds": random.randint(60, 180)
                },
                timeout=5
            )

            if hold_resp.status_code != 201:
                with lock:
                    results["hold_failed"] += 1
                return

            hold_data = hold_resp.json()
            hold_id = hold_data["hold_id"]

            with lock:
                results["hold_success"] += 1

            # Simulate user thinking / payment delay
            time.sleep(random.uniform(0.1, 1.5))

            # Decide whether user books or abandons
            if random.random() < BOOK_PROBABILITY:
                book_resp = requests.post(
                    f"{BASE_URL}/shows/{SHOW_ID}/book",
                    json={"hold_id": hold_id},
                    timeout=5
                )

                if book_resp.status_code == 200:
                    with lock:
                        results["book_success"] += 1
                else:
                    with lock:
                        results["book_failed"] += 1
            else:
                # user abandons booking
                with lock:
                    results["abandoned"] += 1

            return

        except Exception as e:
            time.sleep(0.2)

    with lock:
        results["hold_failed"] += 1


def run_stress_test():
    print(f"\n🚀 Starting stress test with {TOTAL_USERS} concurrent users\n")

    start_time = time.time()

    with ThreadPoolExecutor(max_workers=TOTAL_USERS) as executor:
        futures = [executor.submit(user_flow, i) for i in range(TOTAL_USERS)]
        for _ in as_completed(futures):
            pass

    duration = time.time() - start_time

    print("\n✅ Stress Test Completed")
    print(f"⏱  Duration: {duration:.2f}s\n")

    for k, v in results.items():
        print(f"{k:15}: {v}")

    print("\n📊 Final Seat Status:")
    status = get_seat_status()
    for k, v in status.items():
        print(f"{k:15}: {v}")

    # Critical invariant check
    total = (
    status["available_seats"]
    + status["held_seats"]
    + status["booked_seats"]
)

    print(f"\n🧮 Seat Count Check: {total} total seats")

    if total != status["total_seats"]:
        print("❌ ERROR: Seat count mismatch!")
    else:
        print("✅ Seat count consistent")

    if status["booked_seats"] > status["total_seats"]:
        print("❌ ERROR: Overbooking detected!")
    else:
        print("✅ No overbooking detected")



if __name__ == "__main__":
    run_stress_test()
