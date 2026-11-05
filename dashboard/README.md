# Analytics Administrative Dashboard

Planned for **Milestone M3** (Dashboard & Reporting).

## Role
- React 19 / TypeScript SPA dashboard powered by Vite.
- Secure administrative portal for inspecting cross-application and per-tenant metrics:
  - Real-time event throughput & health
  - Daily/weekly/monthly active visitors & session trends
  - Pageview analytics, top referrers, entry/exit pages
  - Device, OS, browser, and geographic breakdowns
  - Scoped visitor journey timelines
  - Export auditing and compliance logs
- Strict Role-Based Access Control (RBAC) with environment scoping (`test` vs `live`).
- Server-side authentication and session validation (no public unauthenticated metric endpoints).

*Note: Dashboard implementation commences in Milestone M3 following core API and ingestion completion.*
