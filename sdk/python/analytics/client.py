"""Analytics Platform Client (Milestone M4).

Provides non-blocking, fail-open event ingestion for Python servers and workers.
"""

import atexit
import datetime
import logging
import queue
import threading
import time
import uuid
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger("analytics")


class AnalyticsClient:
    """Thread-safe, non-blocking synchronous analytics client with background batch worker."""

    def __init__(
        self,
        endpoint: str,
        write_key: str,
        batch_size: int = 20,
        flush_interval_sec: float = 2.0,
        max_queue_size: int = 1000,
        timeout_sec: float = 4.0,
        enabled: bool = True,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.write_key = write_key
        self.batch_size = max(1, batch_size)
        self.flush_interval_sec = flush_interval_sec
        self.max_queue_size = max_queue_size
        self.timeout_sec = timeout_sec
        self.enabled = enabled and bool(write_key)

        self._queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._http_client = httpx.Client(timeout=self.timeout_sec)

        if self.enabled:
            self._start_worker()
            atexit.register(self.close)

    def _start_worker(self) -> None:
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="analytics-batch-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def track(
        self,
        event_name: str,
        event_type: str = "custom",
        page_path: Optional[str] = None,
        visitor_id: Optional[str] = None,
        session_id: Optional[str] = None,
        referrer: Optional[str] = None,
        duration_ms: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime.datetime] = None,
        source: Optional[str] = "python",
        user_agent: Optional[str] = None,
        country_code: Optional[str] = None,
        device_family: Optional[str] = None,
        browser_family: Optional[str] = None,
        os_family: Optional[str] = None,
    ) -> None:
        """Enqueue a telemetry event. Never raises exceptions (fail-open contract)."""
        if not self.enabled:
            return

        try:
            ts = (timestamp or datetime.datetime.now(datetime.timezone.utc)).isoformat()
            meta = dict(metadata or {})
            if source and "source" not in meta:
                meta["source"] = source

            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": event_type,
                "event_name": event_name,
                "page_path": page_path or "/",
                "visitor_id": visitor_id,
                "session_id": session_id,
                "referrer": referrer,
                "duration_ms": duration_ms,
                "source": source,
                "user_agent": user_agent,
                "country_code": country_code,
                "device_family": device_family,
                "browser_family": browser_family,
                "os_family": os_family,
                "metadata": meta,
                "timestamp": ts,
            }

            try:
                self._queue.put_nowait(event)
            except queue.Full:
                # FIFO drop to preserve memory limits and prevent process memory exhaustion
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(event)
                except queue.Full:
                    pass
        except Exception as e:
            logger.debug(f"Analytics fail-open: track error ignored: {e}")

    def pageview(
        self,
        page_path: str,
        visitor_id: Optional[str] = None,
        session_id: Optional[str] = None,
        referrer: Optional[str] = None,
        duration_ms: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        source: Optional[str] = "python",
        user_agent: Optional[str] = None,
        country_code: Optional[str] = None,
    ) -> None:
        """Convenience helper to record a pageview event."""
        self.track(
            event_name="pageview",
            event_type="pageview",
            page_path=page_path,
            visitor_id=visitor_id,
            session_id=session_id,
            referrer=referrer,
            duration_ms=duration_ms,
            metadata=metadata,
            source=source,
            user_agent=user_agent,
            country_code=country_code,
        )

    def flush(self) -> None:
        """Synchronously drain all currently queued events."""
        if not self.enabled:
            return
        try:
            batch: List[Dict[str, Any]] = []
            while not self._queue.empty():
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
                if len(batch) >= 100:
                    self._send_batch(batch)
                    batch = []
            if batch:
                self._send_batch(batch)
        except Exception as e:
            logger.debug(f"Analytics fail-open: flush error ignored: {e}")

    def close(self) -> None:
        """Gracefully stop worker and flush pending queue."""
        if not self.enabled or self._stop_event.is_set():
            return
        try:
            self._stop_event.set()
            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=1.5)
            self.flush()
            self._http_client.close()
        except Exception as e:
            logger.debug(f"Analytics fail-open: close error ignored: {e}")

    def _worker_loop(self) -> None:
        last_flush = time.time()
        while not self._stop_event.is_set():
            try:
                batch: List[Dict[str, Any]] = []
                while len(batch) < self.batch_size and not self._stop_event.is_set():
                    remaining_time = max(0.1, self.flush_interval_sec - (time.time() - last_flush))
                    try:
                        item = self._queue.get(timeout=remaining_time)
                        batch.append(item)
                    except queue.Empty:
                        break

                now = time.time()
                if batch and (len(batch) >= self.batch_size or (now - last_flush) >= self.flush_interval_sec):
                    self._send_batch(batch)
                    last_flush = now
                elif not batch:
                    last_flush = now
            except Exception as e:
                logger.debug(f"Analytics worker loop error ignored: {e}")

    def _send_batch(self, batch: List[Dict[str, Any]]) -> None:
        if not batch:
            return
        try:
            headers = {
                "Authorization": f"Bearer {self.write_key}",
                "Content-Type": "application/json",
            }
            url = f"{self.endpoint}/v1/events/batch"
            payload = {"batch": batch}
            resp = self._http_client.post(url, json=payload, headers=headers)
            if resp.status_code not in (200, 201, 202):
                logger.debug(f"Analytics API batch response status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.debug(f"Analytics fail-open: batch dispatch failed: {e}")


class AsyncAnalyticsClient:
    """Asynchronous non-blocking analytics client for asyncio applications."""

    def __init__(
        self,
        endpoint: str,
        write_key: str,
        batch_size: int = 20,
        flush_interval_sec: float = 2.0,
        max_queue_size: int = 1000,
        timeout_sec: float = 4.0,
        enabled: bool = True,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.write_key = write_key
        self.batch_size = max(1, batch_size)
        self.flush_interval_sec = flush_interval_sec
        self.max_queue_size = max_queue_size
        self.timeout_sec = timeout_sec
        self.enabled = enabled and bool(write_key)

        import asyncio
        self._queue: Optional[asyncio.Queue] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._closing = False

    async def _ensure_started(self) -> None:
        import asyncio
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self.max_queue_size)
            self._http_client = httpx.AsyncClient(timeout=self.timeout_sec)
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def track(
        self,
        event_name: str,
        event_type: str = "custom",
        page_path: Optional[str] = None,
        visitor_id: Optional[str] = None,
        session_id: Optional[str] = None,
        referrer: Optional[str] = None,
        duration_ms: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime.datetime] = None,
        source: Optional[str] = "python",
        user_agent: Optional[str] = None,
        country_code: Optional[str] = None,
        device_family: Optional[str] = None,
        browser_family: Optional[str] = None,
        os_family: Optional[str] = None,
    ) -> None:
        """Enqueue an event asynchronously. Never raises exceptions (fail-open)."""
        if not self.enabled or self._closing:
            return

        try:
            await self._ensure_started()
            ts = (timestamp or datetime.datetime.now(datetime.timezone.utc)).isoformat()
            meta = dict(metadata or {})
            if source and "source" not in meta:
                meta["source"] = source

            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": event_type,
                "event_name": event_name,
                "page_path": page_path or "/",
                "visitor_id": visitor_id,
                "session_id": session_id,
                "referrer": referrer,
                "duration_ms": duration_ms,
                "source": source,
                "user_agent": user_agent,
                "country_code": country_code,
                "device_family": device_family,
                "browser_family": browser_family,
                "os_family": os_family,
                "metadata": meta,
                "timestamp": ts,
            }

            try:
                self._queue.put_nowait(event)
            except Exception:
                # Drop oldest if full
                if not self._queue.empty():
                    self._queue.get_nowait()
                self._queue.put_nowait(event)
        except Exception as e:
            logger.debug(f"Async analytics fail-open track error: {e}")

    async def pageview(
        self,
        page_path: str,
        visitor_id: Optional[str] = None,
        session_id: Optional[str] = None,
        referrer: Optional[str] = None,
        duration_ms: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        source: Optional[str] = "python",
        user_agent: Optional[str] = None,
        country_code: Optional[str] = None,
    ) -> None:
        await self.track(
            event_name="pageview",
            event_type="pageview",
            page_path=page_path,
            visitor_id=visitor_id,
            session_id=session_id,
            referrer=referrer,
            duration_ms=duration_ms,
            metadata=metadata,
            source=source,
            user_agent=user_agent,
            country_code=country_code,
        )

    async def flush(self) -> None:
        if not self.enabled or self._queue is None:
            return
        try:
            batch = []
            while not self._queue.empty():
                batch.append(self._queue.get_nowait())
                if len(batch) >= 100:
                    await self._send_batch(batch)
                    batch = []
            if batch:
                await self._send_batch(batch)
        except Exception as e:
            logger.debug(f"Async flush error ignored: {e}")

    async def close(self) -> None:
        if not self.enabled or self._closing:
            return
        self._closing = True
        try:
            if self._worker_task:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except Exception:
                    pass
            await self.flush()
            if self._http_client:
                await self._http_client.aclose()
        except Exception as e:
            logger.debug(f"Async close error ignored: {e}")

    async def _worker_loop(self) -> None:
        import asyncio
        last_flush = time.time()
        while not self._closing:
            try:
                batch = []
                while len(batch) < self.batch_size and not self._closing:
                    try:
                        item = await asyncio.wait_for(self._queue.get(), timeout=self.flush_interval_sec)
                        batch.append(item)
                    except asyncio.TimeoutError:
                        break

                if batch:
                    await self._send_batch(batch)
                    last_flush = time.time()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Async worker loop error: {e}")
                await asyncio.sleep(0.5)

    async def _send_batch(self, batch: List[Dict[str, Any]]) -> None:
        if not batch or not self._http_client:
            return
        try:
            headers = {
                "Authorization": f"Bearer {self.write_key}",
                "Content-Type": "application/json",
            }
            url = f"{self.endpoint}/v1/events/batch"
            payload = {"batch": batch}
            resp = await self._http_client.post(url, json=payload, headers=headers)
            if resp.status_code not in (200, 201, 202):
                logger.debug(f"Async API batch status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.debug(f"Async batch dispatch failed: {e}")
