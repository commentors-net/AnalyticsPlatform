# Python Analytics SDK

Planned for **Milestone M4** (Integration SDKs).

## Role
- Client library for Python server applications (FastAPI, Flask, Django, Celery).
- Server-side event tracking, background worker telemetry, API route performance tracking.
- Non-blocking, asynchronous execution (asyncio worker thread or thread pool executor).
- Fail-open contract: failures in analytics dispatch must never block host application requests.
- Environment-aware routing (`test` vs `live`) with dedicated write keys.

*Note: Python SDK implementation commences in Milestone M4.*
