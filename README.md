# 🎬 Movie Show Seat Management System

![Concurrency Safe](https://img.shields.io/badge/concurrency-safe-brightgreen)
![PostgreSQL](https://img.shields.io/badge/database-PostgreSQL-336791)
![Flask](https://img.shields.io/badge/framework-Flask-000000)
![License](https://img.shields.io/badge/license-MIT-blue)

A production-grade backend system for managing movie show seat reservations with **strong concurrency guarantees**, **data persistence**, and **automatic cleanup of expired holds**. Designed to handle high-traffic booking scenarios without double-booking or race conditions.

> ✨ **Key Innovation**: Uses PostgreSQL row-level locking (`SELECT FOR UPDATE`) instead of application-level locks for true distributed concurrency safety.

---

## 🌟 Features

| Feature | Implementation | Benefit |
|---------|----------------|---------|
| **Concurrency Safety** | PostgreSQL `SELECT FOR UPDATE` row locking | Prevents double-booking across multiple app instances |
| **Temporary Holds** | Configurable hold duration (default 10 min) | Reserves seats while users complete payment |
| **Auto Cleanup** | Background job + on-demand expiration checks | Recovers seats from abandoned carts |
| **Data Persistence** | PostgreSQL ACID-compliant storage | Survives restarts, crashes, deployments |
| **State Integrity** | Database constraints + invariant checks | Guarantees seat count accuracy |
| **Health Monitoring** | `/health` endpoint with DB connectivity check | Production observability |
| **Docker Ready** | Single-command deployment | Consistent dev/prod environments |

---

## 📁 Project Structure

```
seat-management-system/
├── app.py                 # Flask application & API endpoints
├── database_manager.py    # Core business logic & DB operations
├── models.py              # SQLAlchemy data models
├── requirements.txt       # Python dependencies
├── docker-compose.yml     # PostgreSQL + App orchestration
├── Dockerfile             # Application container definition
├── .env.example           # Environment variables template
├── README.md              # This file
└── templates/
    └── home.html          # Simple demo UI (optional)
```

---

## 🚀 Setup Instructions

### Option 1: Docker Compose (Recommended - 2 Minutes)

Perfect for development, testing, or quick deployment:

```bash
# 1. Clone repository
git clone https://github.com/yourusername/seat-management-system.git
cd seat-management-system

# 2. Copy environment template
cp .env.example .env

# 3. Start services (PostgreSQL + Flask app)
docker-compose up --build

# 4. Verify system is healthy
curl http://localhost:5000/health
# Should return: {"status": "healthy", "database": "connected", "shows": 1}
```

✅ **Done!** System is running with:
- PostgreSQL on `localhost:5432`
- API on `http://localhost:5000`
- Pre-initialized demo show: `avengers_2026_7pm` (50 seats)

---

### Option 2: Local Setup (Without Docker)

#### Prerequisites
- Python 3.8+
- PostgreSQL 12+
- pip

#### Steps
```bash
# 1. Create PostgreSQL database
psql -U postgres
CREATE DATABASE seat_management;
CREATE USER seat_user WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE seat_management TO seat_user;
\q

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
echo "DATABASE_URL=postgresql://seat_user:secure_password@localhost:5432/seat_management" > .env

# 4. Start application
python app.py
```

---

## 📡 API Documentation

### Quick Test Flow (Using Demo Show)
```bash
# 1. Check available seats
curl http://localhost:5000/shows/avengers_2026_7pm/seats

# 2. Hold seats A1 and A2 (returns hold_id)
HOLD_ID=$(curl -s -X POST http://localhost:5000/shows/avengers_2026_7pm/hold \
  -H "Content-Type: application/json" \
  -d '{"seat_ids": ["A1", "A2"]}' | jq -r '.hold_id')

# 3. Book the held seats
curl -X POST http://localhost:5000/shows/avengers_2026_7pm/book \
  -H "Content-Type: application/json" \
  -d "{\"hold_id\": \"$HOLD_ID\"}"

# 4. Verify seats are now BOOKED
curl http://localhost:5000/shows/avengers_2026_7pm/seats
```

### Full Endpoint Reference

| Endpoint | Method | Description | Critical Notes |
|----------|--------|-------------|----------------|
| `/shows/<id>/initialize` | POST | Create new show with seats | Idempotent; fails if show exists |
| `/shows/<id>/seats` | GET | Get real-time seat status | Includes counts + per-seat details |
| `/shows/<id>/hold` | POST | Reserve seats temporarily | Returns `hold_id`; seats locked for duration |
| `/shows/<id>/book` | POST | Confirm booking | **Requires valid hold_id**; atomic transition |
| `/shows/<id>/release-hold` | POST | Cancel hold early | Releases seats immediately |
| `/health` | GET | System health check | Verifies DB connectivity + show counts |

📌 **All timestamps are UTC**  
📌 **Seat IDs are case-sensitive strings** (e.g., `"A1"`, `"ROW3_SEAT15"`)  
📌 **Hold duration**: Clamped between 60-1800 seconds (1-30 minutes)

---

## 🔒 Production Deployment Checklist

Before deploying to production:

- [ ] **Change default credentials** in `docker-compose.yml` and `.env`
- [ ] **Enable SSL** for PostgreSQL connections (`sslmode=require`)
- [ ] **Set up database backups** (pg_dump + cloud storage)
- [ ] **Add API authentication** (JWT/OAuth2) - *outside current scope*
- [ ] **Configure connection pooling** (PgBouncer for high traffic)
- [ ] **Add rate limiting** (Flask-Limiter) to prevent abuse
- [ ] **Enable monitoring** (Prometheus metrics endpoint)
- [ ] **Set up log aggregation** (ELK stack or Datadog)
- [ ] **Tune PostgreSQL** (`shared_buffers`, `work_mem`)
- [ ] **Use Gunicorn** instead of Flask dev server:
  ```bash
  gunicorn -w 4 -b 0.0.0.0:5000 app:app
  ```

---

## 🤔 Why This Architecture?

| Challenge | Solution | Why It Works |
|-----------|----------|--------------|
| **Double-booking** | `SELECT ... FOR UPDATE` | Database locks rows until transaction commits |
| **Abandoned carts** | Background cleanup + on-demand checks | Seats recovered within seconds of expiration |
| **System restarts** | PostgreSQL durability | All bookings persist through crashes |
| **Multiple app instances** | Database as source of truth | No shared memory needed between instances |
| **Seat count integrity** | Database constraints + counts query | Prevents invalid states at storage layer |

> 💡 **Critical Insight**: Application-level locks (like `threading.RLock`) fail in distributed systems. By moving concurrency control to PostgreSQL, we achieve true horizontal scalability.

---

## 🧪 Testing Recommendations

1. **Concurrency Test** (using `hey`):
   ```bash
   # Simulate 100 users trying to book same seat simultaneously
   hey -n 100 -c 50 -m POST -d '{"seat_ids":["A1"]}' \
       http://localhost:5000/shows/avengers_2026_7pm/hold
   ```
   ✅ **Expected**: Only 1 request succeeds; others get "seats unavailable"

2. **Expiration Test**:
   ```bash
   # Hold seat with 10-second duration
   curl -X POST http://localhost:5000/shows/test/hold \
     -H "Content-Type: application/json" \
     -d '{"seat_ids":["Z99"], "hold_duration_seconds":10}'
   
   # Wait 15 seconds, then try to book
   curl -X POST http://localhost:5000/shows/test/book \
     -H "Content-Type: application/json" \
     -d '{"hold_id":"<ID>"}'
   ```
   ✅ **Expected**: Booking fails with "hold expired"; seat becomes available

---

## 📜 License

MIT License - See [LICENSE](LICENSE) file for details

---

## 💬 Support & Contribution

- 🐛 **Found a bug?** Open an issue with steps to reproduce
- 💡 **Feature request?** Submit a proposal in Discussions
- 🌍 **Using in production?** Let us know! We'd love to hear your story

> ✨ **Remember**: This system handles *only seat management*. Integrate with your payment, auth, and notification systems for a complete ticketing solution.

---

**Happy Booking! 🍿**  
*Engineered for reliability in high-stakes reservation scenarios*