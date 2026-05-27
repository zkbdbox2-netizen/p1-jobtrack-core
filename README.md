# P1 — JobTrack Core API

A production-grade REST API for tracking job applications through a hiring pipeline.
Built with FastAPI, PostgreSQL, and Redis. Part of the [AI Job Tracker](../README.md) portfolio.

**Key features:** JWT auth with refresh token rotation · Multi-tenant row isolation ·
Two-field pipeline model (stage × outcome) · Cursor-based pagination · Prometheus metrics ·
Structured JSON logging · 23-test async test suite

---

## Architecture

```mermaid
flowchart TD
    Client(["Client\n(browser / curl)"])

    subgraph FastAPI ["FastAPI (uvicorn)"]
        direction TB
        PM["Prometheus Middleware\nrecords latency + count"]
        CM["Correlation ID Middleware\nattaches request ID to logs"]
        Auth["POST /auth/register\nPOST /auth/login\nPOST /auth/refresh\nPOST /auth/logout"]
        Jobs["GET  /jobs\nPOST /jobs\nGET  /jobs/:id\nPATCH /jobs/:id\nDELETE /jobs/:id"]
        Ops["GET /health\nGET /metrics"]
    end

    PG[("PostgreSQL 16\nusers · jobs")]
    Redis[("Redis 7\nrefresh token JTIs")]
    Prom(["Prometheus scraper\n(external)"])

    Client -->|"HTTP request"| PM
    PM --> CM
    CM --> Auth & Jobs & Ops
    Auth -->|"SELECT / INSERT users"| PG
    Auth -->|"SET / DEL JTI"| Redis
    Jobs -->|"SELECT / INSERT / UPDATE jobs\nWHERE tenant_id = $user"| PG
    Ops -->|"generate_latest()"| Prom
```

---

## Request flow (auth example)

```mermaid
sequenceDiagram
    participant C as Client
    participant API as FastAPI
    participant PG as PostgreSQL
    participant R as Redis

    C->>API: POST /auth/login {email, password}
    API->>PG: SELECT user WHERE email = $1
    PG-->>API: user row (hashed_password)
    API->>API: bcrypt.checkpw(password, hash)
    API->>API: sign access_token JWT (15 min)
    API->>API: sign refresh_token JWT (7 days)
    API->>R: SET jti → user_id (TTL 7d)
    API-->>C: {access_token, refresh_token}

    Note over C,API: Later — access token expires

    C->>API: POST /auth/refresh {refresh_token}
    API->>API: verify JWT signature + expiry
    API->>R: GET jti (must exist)
    R-->>API: user_id
    API->>R: DEL old jti
    API->>API: issue new token pair
    API->>R: SET new jti → user_id (TTL 7d)
    API-->>C: {access_token, refresh_token}
```

---

## Project structure

```
P1-JobTrack-Core/
├── app/
│   ├── auth/           # register, login, refresh, logout routes + JWT service
│   ├── models/         # SQLAlchemy ORM models (User, Job) + base mixins
│   ├── routers/        # Job CRUD routes
│   ├── schemas/        # Pydantic request/response schemas
│   ├── services/       # Business logic (job CRUD, cursor pagination)
│   ├── config.py       # Settings loaded from .env via pydantic-settings
│   ├── dependencies.py # FastAPI Depends factories (get_db, get_redis, get_current_user)
│   ├── main.py         # App factory, middleware, /health + /metrics
│   └── metrics.py      # Prometheus metric definitions
├── alembic/            # Database migrations
├── tests/
│   ├── conftest.py     # Fixtures: engine (NullPool), db, fake_redis, client, auth helpers
│   ├── test_auth.py    # 9 auth tests
│   └── test_jobs.py    # 14 job tests (incl. tenant isolation + cursor pagination)
├── DESIGN.md           # Architecture decisions and trade-offs
├── docker-compose.yml  # App + Postgres 16 + Redis 7
├── Dockerfile
└── pyproject.toml
```

---

## Quick start

```bash
# 1. Copy environment file
cp .env.example .env          # edit SECRET_KEY before deploying

# 2. Start all services
make up

# 3. Run database migrations
make migrate

# 4. Verify the service
curl http://localhost:8000/health
# {"status":"ok","version":"0.1.0","environment":"development"}

# 5. Run the test suite
make test
```

---

## API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/register` | — | Create account, returns token pair |
| POST | `/auth/login` | — | Login, returns token pair |
| POST | `/auth/refresh` | — | Rotate refresh token |
| POST | `/auth/logout` | — | Revoke refresh token |
| GET | `/jobs` | ✓ | List jobs (cursor pagination, stage/outcome filter) |
| POST | `/jobs` | ✓ | Create job |
| GET | `/jobs/{id}` | ✓ | Get job by ID |
| PATCH | `/jobs/{id}` | ✓ | Partial update |
| DELETE | `/jobs/{id}` | ✓ | Soft delete |
| GET | `/health` | — | Liveness check |
| GET | `/metrics` | — | Prometheus metrics |

---

## Design decisions

See [DESIGN.md](./DESIGN.md) for detailed rationale on:
- Two-field pipeline model (stage × outcome) vs flat status enum
- Cursor-based pagination vs offset/limit
- Stateless access tokens + stateful refresh tokens
- Real Postgres in tests (not SQLite), NullPool, fakeredis
