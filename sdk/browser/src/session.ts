/**
 * Session Lifecycle Manager (M2-06, M2-14, M2-17).
 * Maintains session continuity across navigation with 30-minute idle expiration.
 * Enforces zero session tracking in NO_STORAGE mode.
 */

import { SessionState } from './types';
import { StorageManager } from './storage';

const SESSION_IDLE_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

export class SessionManager {
  private storage: StorageManager;
  private currentSession: SessionState | null = null;

  constructor(storage: StorageManager) {
    this.storage = storage;
    if (this.storage.getConsent() !== 'NO_STORAGE') {
      this.restoreOrInitSession();
    }
  }

  public getSessionId(): string | null {
    if (this.storage.getConsent() === 'NO_STORAGE') {
      return null;
    }
    this.ensureActiveSession();
    return this.currentSession ? this.currentSession.sessionId : null;
  }

  public isReturning(): boolean {
    if (this.storage.getConsent() !== 'ANALYTICS_ALLOWED') {
      return false;
    }
    this.ensureActiveSession();
    return this.currentSession ? this.currentSession.isReturning : false;
  }

  public recordPageview(path: string): void {
    if (this.storage.getConsent() === 'NO_STORAGE') {
      return;
    }
    this.ensureActiveSession(path);
    if (this.currentSession) {
      this.currentSession.pageviewsCount += 1;
      this.currentSession.lastActivity = Date.now();
      this.persistSession();
    }
  }

  public touch(): void {
    if (this.storage.getConsent() === 'NO_STORAGE') {
      return;
    }
    // Check idle expiration BEFORE updating activity timestamp (M2-17)
    this.ensureActiveSession();
    if (this.currentSession) {
      this.currentSession.lastActivity = Date.now();
      this.persistSession();
    }
  }

  public resetSession(): void {
    this.currentSession = null;
    this.storage.clearSessionData();
  }

  private ensureActiveSession(currentPath?: string): boolean {
    const path = currentPath || (typeof window !== 'undefined' && window.location ? window.location.pathname : '/');
    const now = Date.now();
    if (!this.currentSession || (now - this.currentSession.lastActivity > SESSION_IDLE_TIMEOUT_MS)) {
      this.initNewSession(path);
      return true;
    }
    return false;
  }

  private initNewSession(currentPath: string): void {
    const now = Date.now();
    const rawUuid = this.storage.generateUuid().replace(/-/g, '').slice(0, 16);
    this.currentSession = {
      sessionId: `ses_${rawUuid}`,
      startedAt: now,
      lastActivity: now,
      pageviewsCount: 0,
      entryPage: currentPath,
      isReturning: this.storage.isReturningVisitor(),
    };
    this.persistSession();
  }

  private restoreOrInitSession(): void {
    const raw = this.storage.getSessionData();
    if (raw) {
      try {
        const parsed: SessionState = JSON.parse(raw);
        const now = Date.now();
        if (now - parsed.lastActivity <= SESSION_IDLE_TIMEOUT_MS) {
          this.currentSession = parsed;
          return;
        }
      } catch {
        // Corrupted session string
      }
    }
    const currentPath = typeof window !== 'undefined' && window.location ? window.location.pathname : '/';
    this.initNewSession(currentPath);
  }

  private persistSession(): void {
    if (!this.currentSession || this.storage.getConsent() === 'NO_STORAGE') return;
    try {
      this.storage.setSessionData(JSON.stringify(this.currentSession));
    } catch {
      // Fail-open
    }
  }
}
