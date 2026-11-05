/**
 * Type definitions for the Browser Analytics SDK.
 */

export type ConsentLevel = 'NO_STORAGE' | 'ANONYMOUS' | 'ANALYTICS_ALLOWED';

export type EventCategory = 'pageview' | 'custom' | 'click' | 'timing';

export interface TrackerConfig {
  /** The ingestion API endpoint (e.g. 'https://telemetry.askanna.ai' or 'http://localhost:5433') */
  endpoint: string;
  /** Public client-side write key (e.g. 'apk_live_...') */
  writeKey: string;
  /** Initial consent level (default: 'ANONYMOUS') */
  consent?: ConsentLevel;
  /** Whether to automatically track initial pageview and URL changes (default: true) */
  autoPageview?: boolean;
  /** Whether to intercept pushState/replaceState for SPA route changes (default: true) */
  autoSpa?: boolean;
  /** Maximum number of events to buffer before flushing (default: 10) */
  batchSize?: number;
  /** Maximum interval in milliseconds before flushing buffered events (default: 2000) */
  flushIntervalMs?: number;
  /** Maximum retry attempts for failed requests (default: 2) */
  maxRetries?: number;
}

export interface TelemetryEvent {
  event_id: string;
  event_type: EventCategory;
  event_name: string;
  visitor_id?: string | null;
  session_id?: string | null;
  page_path: string;
  referrer?: string | null;
  duration_ms?: number | null;
  metadata?: Record<string, unknown>;
  timestamp: string;
}

export interface SessionState {
  sessionId: string;
  startedAt: number;
  lastActivity: number;
  pageviewsCount: number;
  entryPage: string;
  isReturning: boolean;
}
