/**
 * Three-tier consent and safe storage manager (M2-05, M2-17).
 * Strict fail-open guarantees: explicit host consent is authoritative,
 * private browsing restrictions or quota limits never throw.
 */

import { ConsentLevel } from './types';

const PREFIX = 'ap_';
const VISITOR_KEY = PREFIX + 'vid';
const FIRST_SEEN_KEY = PREFIX + 'fs';
const CONSENT_KEY = PREFIX + 'consent';
const SESSION_KEY = PREFIX + 'ses';

export class StorageManager {
  private consent: ConsentLevel;

  constructor(initialConsent: ConsentLevel = 'ANONYMOUS') {
    // Explicit host opt-out is strictly authoritative and avoids any storage write (M2-05)
    if (initialConsent === 'NO_STORAGE') {
      this.consent = 'NO_STORAGE';
      this.safeRemoveLocal(VISITOR_KEY);
      this.safeRemoveLocal(FIRST_SEEN_KEY);
      this.safeRemoveLocal(CONSENT_KEY);
      this.safeRemoveSession(SESSION_KEY);
      this.safeRemoveSession(CONSENT_KEY);
      return;
    }

    // Check if storage is accessible; if completely disabled, downgrade to NO_STORAGE
    if (!this.isStorageAvailable('session')) {
      this.consent = 'NO_STORAGE';
      return;
    }

    if (initialConsent === 'ANONYMOUS') {
      this.consent = 'ANONYMOUS';
      // An explicit ANONYMOUS configuration cannot be upgraded by stale localStorage
      this.safeRemoveLocal(VISITOR_KEY);
      this.safeRemoveLocal(FIRST_SEEN_KEY);
      this.safeRemoveLocal(CONSENT_KEY);
      // Check if sessionStorage recorded a downgrade to NO_STORAGE
      const sessionConsent = this.safeGetSession(CONSENT_KEY) as ConsentLevel | null;
      if (sessionConsent === 'NO_STORAGE') {
        this.consent = 'NO_STORAGE';
      }
      return;
    }

    // ANALYTICS_ALLOWED: check localStorage availability
    if (!this.isStorageAvailable('local')) {
      this.consent = 'ANONYMOUS';
      return;
    }

    this.consent = initialConsent;
    const savedConsent = this.safeGetLocal(CONSENT_KEY) as ConsentLevel | null;
    if (savedConsent && ['NO_STORAGE', 'ANONYMOUS', 'ANALYTICS_ALLOWED'].includes(savedConsent)) {
      this.consent = savedConsent;
    }
  }

  public getConsent(): ConsentLevel {
    return this.consent;
  }

  public setConsent(level: ConsentLevel): void {
    if (!['NO_STORAGE', 'ANONYMOUS', 'ANALYTICS_ALLOWED'].includes(level)) {
      level = 'NO_STORAGE';
    }
    this.consent = level;

    if (level === 'NO_STORAGE') {
      // Purge all keys from both localStorage and sessionStorage
      this.safeRemoveLocal(VISITOR_KEY);
      this.safeRemoveLocal(FIRST_SEEN_KEY);
      this.safeRemoveLocal(CONSENT_KEY);
      this.safeRemoveSession(SESSION_KEY);
      this.safeRemoveSession(CONSENT_KEY);
    } else if (level === 'ANONYMOUS') {
      // Retain session in sessionStorage only, purge localStorage (M2-05)
      this.safeRemoveLocal(VISITOR_KEY);
      this.safeRemoveLocal(FIRST_SEEN_KEY);
      this.safeRemoveLocal(CONSENT_KEY);
      this.safeSetSession(CONSENT_KEY, level);
    } else if (level === 'ANALYTICS_ALLOWED') {
      this.safeSetLocal(CONSENT_KEY, level);
    }
  }

  public getVisitorId(): string | null {
    if (this.consent !== 'ANALYTICS_ALLOWED') {
      return null;
    }
    const fsRaw = this.safeGetLocal(FIRST_SEEN_KEY);
    const now = Date.now();
    const expiryMs = 365 * 24 * 60 * 60 * 1000;
    if (fsRaw) {
      const fsTime = parseInt(fsRaw, 10);
      if (isNaN(fsTime) || (now - fsTime > expiryMs)) {
        // Expired visitor ID (> 365 days) -> reset (M2-17)
        this.safeRemoveLocal(VISITOR_KEY);
        this.safeRemoveLocal(FIRST_SEEN_KEY);
      }
    }
    let vid = this.safeGetLocal(VISITOR_KEY);
    if (!vid) {
      vid = this.generateUuid();
      this.safeSetLocal(VISITOR_KEY, vid);
      this.safeSetLocal(FIRST_SEEN_KEY, String(now));
    }
    return vid;
  }

  public isReturningVisitor(): boolean {
    if (this.consent !== 'ANALYTICS_ALLOWED') {
      return false;
    }
    const firstSeenStr = this.safeGetLocal(FIRST_SEEN_KEY);
    if (!firstSeenStr) {
      return false;
    }
    try {
      const firstSeen = parseInt(firstSeenStr, 10);
      const now = Date.now();
      // 365-day retention expiry on firstSeen (M2-17)
      if (now - firstSeen > 365 * 24 * 60 * 60 * 1000) {
        this.safeRemoveLocal(FIRST_SEEN_KEY);
        this.safeRemoveLocal(VISITOR_KEY);
        return false;
      }
      // A visitor is returning only if firstSeen is from a previous session (> 30 mins ago) (M2-17)
      return (now - firstSeen) > 30 * 60 * 1000;
    } catch {
      return false;
    }
  }

  public getSessionData(): string | null {
    if (this.consent === 'NO_STORAGE') {
      return null;
    }
    return this.safeGetSession(SESSION_KEY);
  }

  public setSessionData(data: string): void {
    if (this.consent === 'NO_STORAGE') {
      return;
    }
    this.safeSetSession(SESSION_KEY, data);
  }

  public clearSessionData(): void {
    this.safeRemoveSession(SESSION_KEY);
  }

  public generateUuid(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      try {
        return crypto.randomUUID();
      } catch {
        // Fallback
      }
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  private isStorageAvailable(type: 'session' | 'local' = 'session'): boolean {
    try {
      let storage: Storage | null = null;
      if (type === 'local') {
        storage = typeof window !== 'undefined' && window.localStorage
          ? window.localStorage
          : (typeof localStorage !== 'undefined' ? localStorage : null);
      } else {
        storage = typeof window !== 'undefined' && window.sessionStorage 
          ? window.sessionStorage 
          : (typeof sessionStorage !== 'undefined' ? sessionStorage : null);
      }
      if (!storage) return false;
      const testKey = '__ap_test__';
      storage.setItem(testKey, '1');
      storage.removeItem(testKey);
      return true;
    } catch {
      return false;
    }
  }

  // --- Safe Storage Wrappers (Fail-Open) ---

  private safeGetLocal(key: string): string | null {
    try {
      return typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null;
    } catch {
      return null;
    }
  }

  private safeSetLocal(key: string, value: string): void {
    try {
      if (typeof localStorage !== 'undefined') localStorage.setItem(key, value);
    } catch {
      // Fail-open
    }
  }

  private safeRemoveLocal(key: string): void {
    try {
      if (typeof localStorage !== 'undefined') localStorage.removeItem(key);
    } catch {
      // Fail-open
    }
  }

  private safeGetSession(key: string): string | null {
    try {
      return typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(key) : null;
    } catch {
      return null;
    }
  }

  private safeSetSession(key: string, value: string): void {
    try {
      if (typeof sessionStorage !== 'undefined') sessionStorage.setItem(key, value);
    } catch {
      // Fail-open
    }
  }

  private safeRemoveSession(key: string): void {
    try {
      if (typeof sessionStorage !== 'undefined') sessionStorage.removeItem(key);
    } catch {
      // Fail-open
    }
  }
}
