/**
 * Non-Blocking Transmission & Batch Queue (M2-06, M2-08, M2-09).
 * Enforces:
 * 1. Safe beacon without URL query credentials (M2-08)
 * 2. Reliable idle timer rearming on enqueue (M2-09)
 * 3. Batch preservation if sendBeacon returns false (M2-09)
 * 4. Bounded batch size (50 events, 60KB keepalive limit) (M2-09)
 * 5. Complete queue purging upon consent withdrawal (M2-06)
 */

import { ConsentLevel, TelemetryEvent, TrackerConfig } from './types';

const MAX_BATCH_EVENTS = 50;
const MAX_QUEUE_CAPACITY = 50;
const MAX_KEEPALIVE_BYTES = 60 * 1024; // 60 KB (under browser 64 KB limit)

export class TransportManager {
  private config: Required<TrackerConfig>;
  private queue: TelemetryEvent[] = [];
  private flushTimer: any = null;
  private isFlushing = false;
  private activeRetryTimers: Set<any> = new Set();

  constructor(config: Required<TrackerConfig>) {
    this.config = config;
    this.attachUnloadHandlers();
  }

  public updateConsent(consent: ConsentLevel): void {
    this.config.consent = consent;
    if (consent === 'NO_STORAGE') {
      this.purgeQueue();
    } else if (consent === 'ANONYMOUS') {
      // Strip visitor_id from any queued events
      for (const ev of this.queue) {
        ev.visitor_id = null;
      }
    }
  }

  public enqueue(event: TelemetryEvent): void {
    if (this.config.consent === 'NO_STORAGE') {
      return;
    }
    if (this.config.consent === 'ANONYMOUS') {
      event.visitor_id = null;
    }

    // Bounded queue: drop oldest events to never exceed queue capacity (M2-09)
    while (this.queue.length >= MAX_QUEUE_CAPACITY) {
      this.queue.shift();
    }
    this.queue.push(event);

    // If no timer is active, ensure one is scheduled so events are never starved (M2-09)
    if (!this.flushTimer) {
      this.scheduleFlush();
    }

    const batchLimit = Math.min(this.config.batchSize, MAX_BATCH_EVENTS);
    if (this.queue.length >= batchLimit) {
      this.flush();
    }
  }

  public purgeQueue(): void {
    // Purge queued events and cancel timer upon consent withdrawal (M2-06)
    this.queue = [];
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    for (const timer of this.activeRetryTimers) {
      clearTimeout(timer);
    }
    this.activeRetryTimers.clear();
  }

  public async flush(isUnload = false): Promise<void> {
    if (this.queue.length === 0 || this.isFlushing) {
      return;
    }

    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }

    const batchLimit = Math.min(this.config.batchSize, MAX_BATCH_EVENTS);
    const batch = this.queue.splice(0, batchLimit);
    this.isFlushing = true;

    try {
      if (isUnload && typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
        const accepted = this.transmitViaBeacon(batch);
        if (!accepted) {
          // If browser rejected beacon (e.g. buffer full), return events to queue (M2-09)
          this.queue.unshift(...batch);
        }
      } else {
        await this.transmitViaFetchWithRetry(batch, 0);
      }
    } catch {
      // Fail-open
    } finally {
      this.isFlushing = false;
      if (this.queue.length > 0) {
        this.scheduleFlush();
      }
    }
  }

  private transmitViaBeacon(batch: TelemetryEvent[]): boolean {
    if (this.config.consent === 'NO_STORAGE') return false;
    if (this.config.consent === 'ANONYMOUS') {
      for (const ev of batch) {
        ev.visitor_id = null;
      }
    }

    try {
      const url = `${this.config.endpoint.replace(/\/+$/, '')}/v1/batch`;
      let currentChunk: TelemetryEvent[] = [];
      let allAccepted = true;

      for (const ev of batch) {
        const testPayload = JSON.stringify({ batch: [...currentChunk, ev], write_key: this.config.writeKey });
        if (new Blob([testPayload]).size > MAX_KEEPALIVE_BYTES && currentChunk.length > 0) {
          const chunkPayload = JSON.stringify({ batch: currentChunk, write_key: this.config.writeKey });
          const blob = new Blob([chunkPayload], { type: 'text/plain' });
          if (!navigator.sendBeacon(url, blob)) {
            allAccepted = false;
          }
          currentChunk = [ev];
        } else {
          currentChunk.push(ev);
        }
      }

      if (currentChunk.length > 0) {
        const chunkPayload = JSON.stringify({ batch: currentChunk, write_key: this.config.writeKey });
        const blob = new Blob([chunkPayload], { type: 'text/plain' });
        if (!navigator.sendBeacon(url, blob)) {
          allAccepted = false;
        }
      }

      return allAccepted;
    } catch {
      return false;
    }
  }

  private async transmitViaFetchWithRetry(batch: TelemetryEvent[], retryCount: number): Promise<void> {
    if (this.config.consent === 'NO_STORAGE') {
      return;
    }
    if (this.config.consent === 'ANONYMOUS') {
      for (const ev of batch) {
        ev.visitor_id = null;
      }
    }

    const url = `${this.config.endpoint.replace(/\/+$/, '')}/v1/batch`;
    const payload = JSON.stringify({ batch, write_key: this.config.writeKey });

    const payloadBytes = new Blob([payload]).size;
    const useKeepalive = payloadBytes <= MAX_KEEPALIVE_BYTES;

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Write-Key': this.config.writeKey,
        },
        body: payload,
        keepalive: useKeepalive,
      });

      if (!response.ok && retryCount < this.config.maxRetries) {
        if (response.status >= 500 || response.status === 429) {
          const delay = Math.pow(2, retryCount) * 500;
          let timer: any = null;
          timer = setTimeout(() => {
            this.activeRetryTimers.delete(timer);
            this.transmitViaFetchWithRetry(batch, retryCount + 1);
          }, delay);
          this.activeRetryTimers.add(timer);
        }
      }
    } catch {
      if (retryCount < this.config.maxRetries) {
        const delay = Math.pow(2, retryCount) * 500;
        let timer: any = null;
        timer = setTimeout(() => {
          this.activeRetryTimers.delete(timer);
          this.transmitViaFetchWithRetry(batch, retryCount + 1);
        }, delay);
        this.activeRetryTimers.add(timer);
      }
    }
  }

  private scheduleFlush(): void {
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
    }
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      this.flush();
    }, this.config.flushIntervalMs);
  }

  private attachUnloadHandlers(): void {
    if (typeof window === 'undefined') return;

    const handleUnload = () => {
      if (this.queue.length > 0) {
        this.flush(true);
      }
    };

    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') {
          handleUnload();
        }
      });
    }

    window.addEventListener('beforeunload', handleUnload);
  }
}
