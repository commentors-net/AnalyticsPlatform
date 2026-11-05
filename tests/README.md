# Test Suite & Verification Framework

Planned across all implementation milestones (**M1–M5**).

## Structure
- `unit/`: Unit tests for API handlers, SDK utilities, PII sanitizers, GeoIP parsers, and token handlers.
- `integration/`: Database integration tests, Alembic migration and rollback tests, transaction durability tests.
- `e2e/`: End-to-end ingestion pipelines, browser SDK beacon simulations, dashboard metric aggregations.
- `security/`: Negative authorization tests, tenant isolation breach attempts, SQL injection probes, origin spoofing tests, secret-exposure linters.
- `load/`: Throughput and concurrency benchmarks (Locust/k6) ensuring bounded database connection handling.

*Note: Test implementation begins in Milestone M1.*
