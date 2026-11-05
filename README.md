# Analytics Platform

> Self-Hosted, Privacy-Preserving, Multi-Application Analytics Platform

A high-performance, developer-friendly telemetry and web analytics solution built for multi-tenant environments. Engineered with direct database durability, PostgreSQL Row-Level Security (RLS), declarative partitioning, a three-tier consent model, and strict fail-open client libraries.

---

## Architecture Overview

- **Ingestion API (`api/`):** FastAPI + SQLAlchemy 2.0 (asyncpg) backend with bounded connection pooling, real-time sanitization, in-memory rate limiting, and durable writes to PostgreSQL 16.
- **Browser SDK (`sdk/browser/`):** Lightweight (< 3.5 KB gzipped), zero-dependency TypeScript library with automatic pageview tracking, SPA route interception, three-tier consent (`NO_STORAGE`, `ANONYMOUS`, `ANALYTICS_ALLOWED`), and `sendBeacon` fallback.
- **PostgreSQL 16 Storage Engine:** Declarative monthly partitioning on `events`, composite primary keys `(event_id, timestamp)`, and granular RLS enforcing absolute tenant data isolation.
- **Dashboard (`dashboard/`):** TypeScript React analytics dashboard (planned for Milestone M3).
- **Python SDK (`sdk/python/`):** Server-side telemetry library (planned for Milestone M4).

---

## Privacy & Security Guarantees

1. **Zero Raw IP Persistence:** All client IP addresses are masked to `/24` (IPv4) or `/48` (IPv6) in volatile RAM before storage. Raw IPs never touch disk.
2. **Three-Tier Consent Model:**
   - `NO_STORAGE`: Purely ephemeral, zero cookies, zero `localStorage`/`sessionStorage`.
   - `ANONYMOUS`: `sessionStorage` only, tab-lifecycle bound.
   - `ANALYTICS_ALLOWED`: Pseudonymous UUID stored in first-party `localStorage`.
3. **No Fingerprinting:** Canvas, WebGL, audio, and device fingerprinting techniques are strictly prohibited.
4. **Automatic Credential Scrubbing:** Ingestion pipelines and client libraries automatically sanitize URL query parameters (`token`, `auth`, `password`, `key`, `secret`, `ssn`) and reject prohibited domain data (e.g. VINs, customer chat logs).
5. **Fail-Open Design:** Client libraries and beacons never block host applications or throw unhandled exceptions.

---

## Local Development Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.10+
- Node.js 20+

### 1. Start Isolated PostgreSQL 16
```bash
docker compose -f infra/docker-compose.yml up -d
```
*(Runs on host port `5433` to prevent collisions with other local databases).*

### 2. Setup Python Environment & Run Migrations
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r api/requirements.txt
alembic -c api/alembic.ini upgrade head
```

### 3. Run Backend API
```bash
uvicorn api.app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Build Browser SDK
```bash
cd sdk/browser
npm install
npm run build
```

### 5. Run Automated Tests
```bash
# Python backend & integration tests
pytest -v --cov=api/app

# Browser SDK tests
cd sdk/browser && npm test
```

---

## Documentation

- [Architecture Specifications](docs/architecture/)
- [Architecture Decision Records (ADRs)](docs/adr/)
- [API Contracts](docs/architecture/API_CONTRACTS.md)
- [Privacy & Consent Specification](docs/architecture/PRIVACY_AND_CONSENT.md)
- [Threat Model](docs/architecture/THREAT_MODEL.md)
- [Implementation Plan](docs/ai/IMPLEMENTATION_PLAN.md)

---

## License
Apache-2.0
