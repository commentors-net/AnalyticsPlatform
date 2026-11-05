# Analytics Ingestion & Processing API

Planned for **Milestone M1** (Foundation) and **Milestone M2** (Tracking & Ingestion).

## Role
- Standalone FastAPI application serving:
  - Public ingestion endpoints (`POST /v1/events`, `POST /v1/batch`)
  - Health check & probe endpoints (`GET /health/live`, `GET /health/ready`)
  - Internal administrative / metric endpoints for dashboard queries (if co-located or via dashboard backend)
- High-concurrency, asynchronous I/O using `asyncpg`.
- Bounded database connection pooling and fail-safe error handling.
- Implements strict validation, payload sanitization, GeoIP resolution, and bot filtering.

*Note: Application implementation commences in Milestone M1 following user approval of M0 architecture.*
