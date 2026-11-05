/**
 * Core Browser Analytics Tracker.
 * Integrates three-tier consent, session lifecycle, SPA route interception,
 * sanitization, and fail-open telemetry dispatch.
 */

import { detectClientAutomation } from './bot';
import { sanitizeMetadata, sanitizeReferrer, sanitizeUrlPath } from './sanitizer';
import { SessionManager } from './session';
import { StorageManager } from './storage';
import { TransportManager } from './transport';
import { ConsentLevel, EventCategory, TelemetryEvent, TrackerConfig } from './types';

export class AnalyticsTracker {
  private config: Required<TrackerConfig>;
  private storage: StorageManager;
  private session: SessionManager;
  private transport: TransportManager;
  private lastTrackedPath: string | null = null;
  private isInitialized = false;

  constructor(config: TrackerConfig) {
    this.config = {
      endpoint: config.endpoint,
      writeKey: config.writeKey,
      consent: config.consent || 'ANONYMOUS',
      autoPageview: config.autoPageview !== false,
      autoSpa: config.autoSpa !== false,
      batchSize: config.batchSize || 10,
      flushIntervalMs: config.flushIntervalMs || 2000,
      maxRetries: config.maxRetries ?? 2,
    };

    this.storage = new StorageManager(this.config.consent);
    this.session = new SessionManager(this.storage);
    this.transport = new TransportManager(this.config);

    if (this.config.autoPageview) {
      this.initAutoPageview();
    }

    if (this.config.autoSpa) {
      this.initSpaRouting();
    }

    this.isInitialized = true;
  }

  /** Track a page view with automatic path detection and sanitization */
  public trackPageview(path?: string, metadata?: Record<string, unknown>): void {
    try {
      const rawPath = path || (typeof window !== 'undefined' && window.location ? window.location.pathname + window.location.search + (window.location.hash || '') : '/');
      const cleanPath = sanitizeUrlPath(rawPath);
      this.lastTrackedPath = cleanPath;

      this.session.recordPageview(cleanPath);

      this.dispatchEvent({
        event_type: 'pageview',
        event_name: 'page_view',
        page_path: cleanPath,
        metadata,
      });
    } catch {
      // Fail-open: telemetry exceptions must never disrupt the host app
    }
  }

  /** Track a custom event (e.g. button click, form submission, feature engagement) */
  public trackEvent(
    name: string,
    category: EventCategory = 'custom',
    metadata?: Record<string, unknown>,
    durationMs?: number,
  ): void {
    try {
      const rawPath = typeof window !== 'undefined' && window.location ? window.location.pathname + window.location.search + (window.location.hash || '') : '/';
      const cleanPath = sanitizeUrlPath(rawPath);

      this.session.touch();

      this.dispatchEvent({
        event_type: category,
        event_name: name,
        page_path: cleanPath,
        duration_ms: durationMs,
        metadata,
      });
    } catch {
      // Fail-open
    }
  }

  /** Update consent level (NO_STORAGE, ANONYMOUS, ANALYTICS_ALLOWED) */
  public setConsent(level: ConsentLevel): void {
    try {
      this.storage.setConsent(level);
      this.transport.updateConsent(level);
      if (level === 'NO_STORAGE' || level === 'ANONYMOUS') {
        this.session.resetSession();
      }
    } catch {
      // Fail-open
    }
  }

  public getConsent(): ConsentLevel {
    try {
      return this.storage.getConsent();
    } catch {
      return 'NO_STORAGE';
    }
  }

  /** Manually flush queued telemetry events */
  public async flush(): Promise<void> {
    try {
      await this.transport.flush();
    } catch {
      // Fail-open
    }
  }

  private dispatchEvent(params: {
    event_type: EventCategory;
    event_name: string;
    page_path: string;
    duration_ms?: number;
    metadata?: Record<string, unknown>;
  }): void {
    const isAutomated = detectClientAutomation();
    const rawMetadata = params.metadata || {};
    const safeMetadata = sanitizeMetadata(rawMetadata);

    if (isAutomated) {
      safeMetadata['is_automated'] = true;
    }
    safeMetadata['is_returning'] = this.session.isReturning();

    const rawReferrer = typeof document !== 'undefined' ? document.referrer : null;
    const cleanReferrer = sanitizeReferrer(rawReferrer);

    const event: TelemetryEvent = {
      event_id: this.storage.generateUuid(),
      event_type: params.event_type,
      event_name: params.event_name,
      visitor_id: this.storage.getVisitorId(),
      session_id: this.session.getSessionId(),
      page_path: params.page_path,
      referrer: cleanReferrer,
      duration_ms: params.duration_ms || null,
      metadata: safeMetadata,
      timestamp: new Date().toISOString(),
    };

    this.transport.enqueue(event);
  }

  private initAutoPageview(): void {
    if (typeof window === 'undefined') return;

    if (document.readyState === 'complete' || document.readyState === 'interactive') {
      this.trackPageview();
    } else {
      window.addEventListener('DOMContentLoaded', () => {
        this.trackPageview();
      });
    }
  }

  private initSpaRouting(): void {
    if (typeof window === 'undefined' || !window.history) return;

    const onUrlChange = () => {
      const currentPath = sanitizeUrlPath(window.location.pathname + window.location.search + (window.location.hash || ''));
      if (currentPath !== this.lastTrackedPath) {
        this.trackPageview(currentPath);
      }
    };

    // Intercept history.pushState
    const originalPushState = window.history.pushState;
    if (originalPushState) {
      window.history.pushState = function (...args) {
        const ret = originalPushState.apply(this, args);
        try {
          onUrlChange();
        } catch {}
        return ret;
      };
    }

    // Intercept history.replaceState
    const originalReplaceState = window.history.replaceState;
    if (originalReplaceState) {
      window.history.replaceState = function (...args) {
        const ret = originalReplaceState.apply(this, args);
        try {
          onUrlChange();
        } catch {}
        return ret;
      };
    }

    // Listen to popstate and hashchange
    window.addEventListener('popstate', onUrlChange);
    window.addEventListener('hashchange', onUrlChange);
  }
}
