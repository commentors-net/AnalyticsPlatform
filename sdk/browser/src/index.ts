/**
 * Browser Analytics SDK Entry Point.
 */

import { AnalyticsTracker } from './tracker';
import { ConsentLevel, EventCategory, TrackerConfig } from './types';

export * from './types';
export { AnalyticsTracker } from './tracker';
export { StorageManager } from './storage';
export { SessionManager } from './session';
export { TransportManager } from './transport';
export { sanitizeUrlPath, sanitizeReferrer, sanitizeMetadata } from './sanitizer';

let globalInstance: AnalyticsTracker | null = null;

export function initAnalytics(config: TrackerConfig): AnalyticsTracker {
  if (!globalInstance) {
    globalInstance = new AnalyticsTracker(config);
    if (typeof window !== 'undefined') {
      (window as any).analytics = globalInstance;
    }
  }
  return globalInstance;
}

export function getAnalytics(): AnalyticsTracker | null {
  return globalInstance;
}

// Auto-initialize if script attributes are present
if (typeof document !== 'undefined') {
  try {
    const currentScript = document.currentScript || document.querySelector('script[data-write-key]');
    if (currentScript) {
      const writeKey = currentScript.getAttribute('data-write-key');
      const endpoint = currentScript.getAttribute('data-endpoint') || 'http://localhost:5433';
      const consent = (currentScript.getAttribute('data-consent') as ConsentLevel) || 'ANONYMOUS';

      if (writeKey) {
        initAnalytics({
          endpoint,
          writeKey,
          consent,
        });
      }
    }
  } catch {
    // Fail-open
  }
}
