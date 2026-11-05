# Browser JavaScript / TypeScript Analytics SDK

Planned for **Milestone M2** (Tracking & Ingestion) and refined in **Milestone M4** (Integration SDKs).

## Role
- Lightweight (< 5 KB gzipped), zero-dependency client library for modern browsers.
- Fail-open architecture: under no circumstances will tracking network errors or script exceptions disrupt host application execution.
- Configurable consent modes:
  - `NO_STORAGE` / Ephemeral mode
  - `ANONYMOUS` (session-only, daily rotating salt)
  - `ANALYTICS_ALLOWED` (persistent pseudonymous first-party UUID)
- Automatic pageview tracking, custom event dispatch, outbound link tracking, and performance timings.
- In-memory event batching with `navigator.sendBeacon` fallback for unload events.
- Strict PII filtering: automatic scrubbing of query parameters containing secrets/tokens, suppression of input values, and avoidance of device fingerprinting.

*Note: Client SDK implementation commences in Milestone M2.*
