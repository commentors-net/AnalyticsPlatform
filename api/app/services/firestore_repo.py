"""Firestore Repository for AnalyticsPlatform.

Encapsulates all persistence operations for users, applications, API keys,
event ingestion, atomic idempotency claims, session lifecycle,
and analytics reporting aggregations.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from api.app.core.config import settings
from api.app.core.firestore_db import firestore_db, FirestoreDB
from api.app.core.security import get_password_hash
from api.app.services.dashboard_safety import geography
from api.app.services.sanitizer import classify_referrer

logger = logging.getLogger("analytics_platform.repo")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.now(timezone.utc)


class FirestoreRepo:
    def __init__(self, db: Optional[FirestoreDB] = None):
        self.db = db or firestore_db

    def add(self, entity: Any) -> None:
        """Compatibility helper for test fixtures."""
        from api.app.models.user import User, UserAppPermission
        from api.app.models.application import Application
        from api.app.models.api_key import ApiKey

        if isinstance(entity, User):
            role_val = entity.role.value if hasattr(entity.role, "value") else str(entity.role)
            self.create_user(
                email=entity.email,
                password_hash=entity.password_hash,
                role=role_val,
                status=entity.status,
                user_id=str(entity.id),
            )
        elif isinstance(entity, UserAppPermission):
            role_val = entity.granted_role.value if hasattr(entity.granted_role, "value") else str(entity.granted_role)
            self.grant_user_app_permission(
                user_id=str(entity.user_id),
                app_id=entity.app_id,
                role=role_val,
            )
        elif isinstance(entity, Application):
            self.create_app(
                app_id=entity.app_id,
                name=entity.name,
                allowed_origins=entity.allowed_origins,
            )
        elif isinstance(entity, ApiKey):
            env_val = entity.environment.value if hasattr(entity.environment, "value") else str(entity.environment)
            self.create_api_key(
                key_id=str(entity.id),
                app_id=entity.app_id,
                environment=env_val,
                key_hash=entity.key_hash,
                prefix=entity.prefix,
                name=entity.name,
                expires_at=entity.expires_at,
            )

    async def commit(self) -> None:
        """Compatibility helper (no-op for Firestore)."""
        pass

    async def flush(self) -> None:
        """Compatibility helper (no-op for Firestore)."""
        pass

    async def refresh(self, entity: Any) -> None:
        """Compatibility helper (no-op for Firestore)."""
        pass

    # ==========================================================================
    # User Management & Authentication
    # ==========================================================================

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        snaps = self.db.users_col.where("email", "==", email.lower().strip()).limit(1).get()
        if snaps:
            return snaps[0].to_dict()
        return None

    def is_session_revoked(self, user_id: str, token: str) -> bool:
        """Read shared revocation state; never store the usable credential."""
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return self.db.users_col.document(str(user_id)).collection("revoked_sessions").document(token_hash).get().exists

    def revoke_session(self, user_id: str, token: str, expires_at: datetime) -> None:
        """Durably revoke this token only, across instances, before logout succeeds.

        Records live below analytics_users and may be removed after expires_at;
        JWT expiry is verified before revocation lookup, so delayed deletion is safe.
        """
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self.db.users_col.document(str(user_id)).collection("revoked_sessions").document(token_hash).set({
            "expires_at": expires_at,
        })

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        snap = self.db.users_col.document(str(user_id)).get()
        if snap.exists:
            return snap.to_dict()
        return None

    def create_user(
        self,
        email: str,
        role: str = "Viewer",
        status: str = "ACTIVE",
        password_hash: Optional[str] = None,
        google_sub: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        uid = str(user_id) if user_id else str(uuid.uuid4())
        user_data = {
            "id": uid,
            "email": email.lower().strip(),
            "role": role,
            "status": status,
            "google_sub": str(google_sub) if google_sub else None,
            "password_hash": password_hash,
            "last_login_at": None,
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
        }
        self.db.users_col.document(uid).set(user_data)
        return user_data

    def update_user_last_login(self, user_id: str) -> None:
        self.db.users_col.document(str(user_id)).update({
            "last_login_at": _iso_now(),
            "updated_at": _iso_now(),
        })

    def link_google_identity(self, user_id: str, google_sub: str) -> None:
        """Record Google Subject ID and timestamp upon successful verification."""
        self.db.users_col.document(str(user_id)).update({
            "google_sub": str(google_sub),
            "last_login_at": _iso_now(),
            "updated_at": _iso_now(),
        })

    def provision_approved_user(
        self,
        email: str,
        role: str = "Viewer",
        status: str = "ACTIVE",
    ) -> Dict[str, Any]:
        """Provision or ensure an approved Google account is registered."""
        existing = self.get_user_by_email(email)
        if existing:
            return existing
        return self.create_user(
            email=email,
            role=role,
            status=status,
            password_hash=None,
        )

    def list_users(self) -> List[Dict[str, Any]]:
        """List all provisioned users in the system."""
        snaps = self.db.users_col.get()
        return [s.to_dict() for s in snaps]

    def delete_user(self, user_id: str) -> bool:
        """Revoke and delete a user account."""
        ref = self.db.users_col.document(str(user_id))
        if ref.get().exists:
            ref.delete()
            return True
        return False

    def update_user_role(self, user_id: str, role: str) -> bool:
        """Update platform role for an existing user."""
        ref = self.db.users_col.document(str(user_id))
        if ref.get().exists:
            ref.update({
                "role": role,
                "updated_at": _iso_now(),
            })
            return True
        return False

    # ==========================================================================
    # Application Catalog & Permissions
    # ==========================================================================

    def get_app(self, app_id: str) -> Optional[Dict[str, Any]]:
        snap = self.db.apps_col.document(app_id).get()
        if snap.exists:
            return snap.to_dict()
        return None

    def list_apps_for_user(self, user_id: str, is_superadmin: bool = False) -> List[Dict[str, Any]]:
        if is_superadmin:
            snaps = self.db.apps_col.get()
            return [s.to_dict() for s in snaps]

        perm_snaps = self.db.permissions_col.where("user_id", "==", str(user_id)).get()
        app_ids = [p.to_dict().get("app_id") for p in perm_snaps if p.to_dict().get("app_id")]
        if not app_ids:
            return []

        apps = []
        for aid in app_ids:
            app_snap = self.db.apps_col.document(aid).get()
            if app_snap.exists:
                apps.append(app_snap.to_dict())
        return apps

    def create_app(self, app_id: str, name: str, allowed_origins: Optional[str] = None,
                   live_origins: Optional[str] = None, test_origins: Optional[str] = None,
                   classification: str = "UNCLASSIFIED") -> Dict[str, Any]:
        ref = self.db.apps_col.document(app_id)
        if ref.get().exists:
            raise ValueError(f"Application with ID '{app_id}' already exists")

        app_data = {
            "app_id": app_id,
            "name": name,
            "allowed_origins": allowed_origins,
            "live_origins": live_origins,
            "test_origins": test_origins,
            "classification": classification,
            "status": "ACTIVE",
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
        }
        def create(tx):
            existing = ref.get(transaction=tx)
            retired = self.db.deletions_col.document(app_id).get(transaction=tx)
            if existing.exists or retired.exists:
                raise ValueError("Application identifier already exists or is permanently retired")
            tx.create(ref, app_data)
        self.db.run_transaction(create)
        return app_data

    def update_app(self, app_id: str, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ref = self.db.apps_col.document(app_id)
        def update(tx):
            snap = ref.get(transaction=tx)
            if not snap.exists:
                return None
            if snap.to_dict().get("status") == "DELETING":
                raise ValueError("Deletion is in progress; resume cleanup instead")
            data = {**changes, "updated_at": _iso_now()}
            tx.update(ref, data)
            return {**snap.to_dict(), **data}
        return self.db.run_transaction(update)

    def get_user_app_permission(self, user_id: str, app_id: str) -> Optional[Dict[str, Any]]:
        doc_id = f"{user_id}_{app_id}"
        snap = self.db.permissions_col.document(doc_id).get()
        if snap.exists:
            return snap.to_dict()
        return None

    def grant_user_app_permission(self, user_id: str, app_id: str, role: str) -> Dict[str, Any]:
        doc_id = f"{user_id}_{app_id}"
        data = {
            "id": doc_id,
            "user_id": str(user_id),
            "app_id": app_id,
            "granted_role": role,
            "created_at": _iso_now(),
        }
        def grant(tx):
            self._require_writable_app(tx, app_id)
            tx.set(self.db.permissions_col.document(doc_id), data)
        self.db.run_transaction(grant)
        return data

    # ==========================================================================
    # API Write Keys
    # ==========================================================================

    def get_api_key_by_hash(self, key_hash: str) -> Optional[Dict[str, Any]]:
        snap = self.db.api_keys_col.document(key_hash).get()
        if snap.exists:
            return snap.to_dict()
        return None

    def list_api_keys(self, app_id: str, environment: Optional[str] = None) -> List[Dict[str, Any]]:
        snaps = self.db.api_keys_col.where("app_id", "==", app_id).get()
        results = []
        for s in snaps:
            d = s.to_dict()
            if environment and d.get("environment") != environment:
                continue
            results.append(d)
        results.sort(key=lambda k: k.get("created_at") or "", reverse=True)
        return results

    def create_api_key(
        self,
        key_id: str,
        app_id: str,
        environment: str,
        key_hash: str,
        prefix: str,
        name: str,
        expires_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        key_data = {
            "id": str(key_id),
            "app_id": app_id,
            "environment": environment,
            "key_hash": key_hash,
            "prefix": prefix,
            "name": name,
            "status": "ACTIVE",
            "expires_at": expires_at.isoformat() if expires_at else None,
            "revoked_at": None,
            "created_at": _iso_now(),
        }
        def create(tx):
            self._require_writable_app(tx, app_id, active=True)
            tx.set(self.db.api_keys_col.document(key_hash), key_data)
        self.db.run_transaction(create)
        return key_data

    def _require_writable_app(self, tx, app_id, active=False):
        snap = self.db.apps_col.document(app_id).get(transaction=tx)
        data = snap.to_dict() if snap.exists else {}
        if not data or data.get("status") == "DELETING" or (active and data.get("status") != "ACTIVE"):
            raise ValueError("Application is inactive, deleting or no longer exists")
        return data

    def revoke_api_key(self, app_id: str, key_id: str) -> bool:
        snaps = self.db.api_keys_col.where("app_id", "==", app_id).get()
        for s in snaps:
            data = s.to_dict()
            if data.get("id") == str(key_id):
                def revoke(tx):
                    self._require_writable_app(tx, app_id)
                    existing = s.reference.get(transaction=tx)
                    if existing.exists:
                        tx.update(s.reference, {"status": "REVOKED", "revoked_at": _iso_now()})
                self.db.run_transaction(revoke)
                return True
        return False

    # ==========================================================================
    # Event Ingestion, Idempotency Claim & Session Lifecycle
    # ==========================================================================

    def claim_and_ingest_event(
        self,
        app_id: str,
        environment: str,
        event_id: str,
        event_data: Dict[str, Any],
        session_data: Dict[str, Any],
    ) -> bool:
        """Atomically claim idempotency, persist event, and touch session.
        
        Returns True if newly claimed and ingested, or False if duplicate event.
        """
        idempotency_id = f"{app_id}_{environment}_{event_id}"
        idem_ref = self.db.idempotency_col.document(idempotency_id)

        def ingest(tx):
            self._require_writable_app(tx, app_id, active=True)
            duplicate = idem_ref.get(transaction=tx)
            session_ref = self.db.sessions_col(app_id, environment).document(session_data["session_id"])
            session = session_ref.get(transaction=tx)
            if duplicate.exists:
                return False
            record = self._session_record(app_id, environment, session_data, session)
            tx.set(idem_ref, {"app_id": app_id, "environment": environment, "event_id": str(event_id), "claimed_at": _iso_now()})
            tx.set(self.db.events_col(app_id, environment).document(str(event_id)), event_data)
            tx.set(session_ref, record)
            return True
        return self.db.run_transaction(ingest)

    def touch_session(
        self,
        app_id: str,
        environment: str,
        session_data: Dict[str, Any],
    ) -> None:
        """Update or create session record atomically."""
        sess_ref = self.db.sessions_col(app_id, environment).document(session_data["session_id"])
        def touch(tx):
            self._require_writable_app(tx, app_id, active=True)
            snap = sess_ref.get(transaction=tx)
            tx.set(sess_ref, self._session_record(app_id, environment, session_data, snap))
        self.db.run_transaction(touch)

    def _session_record(self, app_id, environment, session_data, snap):
        session_id = session_data["session_id"]

        event_ts = _parse_iso(session_data.get("started_at"))
        is_pageview = int(session_data.get("pageviews_count") or 0)
        page_path = session_data.get("entry_page") or "/"
        reported_dur = int(session_data.get("duration_seconds") or 0)

        # Single-page website engagement: engaged (non-bounce) if duration >= 10s or pageviews > 1
        initial_bounce = False if (reported_dur >= 10 or is_pageview > 1) else True

        if not snap.exists:
            record = {
                "session_id": session_id,
                "app_id": app_id,
                "environment": environment,
                "visitor_id": session_data.get("visitor_id"),
                "started_at": event_ts.isoformat(),
                "ended_at": event_ts.isoformat(),
                "duration_seconds": reported_dur,
                "pageviews_count": is_pageview,
                "events_count": 1,
                "entry_page": page_path,
                "exit_page": page_path,
                "is_bounce": initial_bounce,
                "referrer_domain": session_data.get("referrer_domain"),
                "referrer_category": session_data.get("referrer_category"),
                "country_code": session_data.get("country_code"),
                "geo_source": session_data.get("geo_source"),
                "device_family": session_data.get("device_family"),
                "created_at": _iso_now(),
                "updated_at": _iso_now(),
            }
            return record
        else:
            existing = snap.to_dict()
            ex_start = _parse_iso(existing.get("started_at"))
            ex_end = _parse_iso(existing.get("ended_at"))

            new_start = min(ex_start, event_ts)
            new_end = max(ex_end, event_ts)
            ts_delta = max(0, int((new_end - new_start).total_seconds()))
            ex_dur = int(existing.get("duration_seconds", 0) or 0)
            duration_sec = max(ex_dur, ts_delta, reported_dur)
            new_pv = existing.get("pageviews_count", 0) + is_pageview
            new_events = existing.get("events_count", 1) + 1
            is_bounce = new_pv <= 1

            updates = {
                "started_at": new_start.isoformat(),
                "ended_at": new_end.isoformat(),
                "duration_seconds": duration_sec,
                "pageviews_count": new_pv,
                "events_count": new_events,
                "is_bounce": is_bounce,
                "updated_at": _iso_now(),
            }
            if session_data.get("country_code") and not existing.get("country_code"):
                updates["country_code"] = session_data.get("country_code")
                updates["geo_source"] = session_data.get("geo_source")
            if event_ts < ex_start:
                updates["entry_page"] = page_path
                if session_data.get("referrer_domain"):
                    updates["referrer_domain"] = session_data.get("referrer_domain")
            if event_ts >= ex_end:
                updates["exit_page"] = page_path

            return {**existing, **updates}

    def cleanup_expired_sessions(self, app_id: str, environment: str, retention_days: int = 90) -> int:
        """Prune session records older than retention threshold."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        snaps = self.db.sessions_col(app_id, environment).where("started_at", "<", cutoff).get()
        deleted = 0
        for s in snaps:
            s.reference.delete()
            deleted += 1
        return deleted

    # ==========================================================================
    # Analytics Reporting & Aggregations
    # ==========================================================================

    def _fetch_window_data(
        self,
        app_id: str,
        environment: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Fetch raw events and sessions in time range."""
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()

        # Query events with single-field index on timestamp
        event_snaps = self.db.events_col(app_id, environment).where("timestamp", ">=", start_iso).where("timestamp", "<=", end_iso).get()
        events = [s.to_dict() for s in event_snaps]

        # Query sessions with single-field index on started_at
        session_snaps = self.db.sessions_col(app_id, environment).where("started_at", ">=", start_iso).where("started_at", "<=", end_iso).get()
        sessions = [s.to_dict() for s in session_snaps]

        return events, sessions

    def get_overview_metrics(
        self,
        app_id: str,
        environment: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> Dict[str, Any]:
        """Compute KPI metrics comparing current window against previous period."""
        window_delta = end_dt - start_dt
        prev_start = start_dt - window_delta
        prev_end = start_dt

        curr_events, curr_sessions = self._fetch_window_data(app_id, environment, start_dt, end_dt)
        prev_events, prev_sessions = self._fetch_window_data(app_id, environment, prev_start, prev_end)

        def _compute(events: List[Dict[str, Any]], sessions: List[Dict[str, Any]]):
            pvs = sum(1 for e in events if str(e.get("event_type", "")).lower() == "pageview")

            # Unique visitors: when approved anonymous identifiers are supplied
            has_visitors = any(bool(e.get("visitor_id")) for e in events)
            visitors = len({e.get("visitor_id") for e in events if e.get("visitor_id")})
            vis_available = has_visitors if len(events) > 0 else True

            # Sessions: client-tracked when session_id or visitor_id was provided
            has_explicit_sessions = any(bool(e.get("session_id")) or bool(e.get("visitor_id")) for e in events)
            sess_count = len(sessions)
            sess_available = has_explicit_sessions if len(events) > 0 else True

            bounces = sum(1 for s in sessions if (s.get("is_bounce") is True and s.get("duration_seconds", 0) < 10))
            bounce_rate = round((bounces / sess_count * 100.0), 1) if sess_count > 0 else 0.0
            avg_dur = round(sum(s.get("duration_seconds", 0) for s in sessions) / sess_count, 1) if sess_count > 0 else 0.0
            return pvs, visitors, vis_available, sess_count, sess_available, bounce_rate, avg_dur

        cpv, cvis, cvis_avail, cses, cses_avail, cbr, cdur = _compute(curr_events, curr_sessions)
        ppv, pvis, pvis_avail, pses, pses_avail, pbr, pdur = _compute(prev_events, prev_sessions)

        def _pct(c: float, p: float) -> float:
            if p == 0:
                return 100.0 if c > 0 else 0.0
            return round(((c - p) / p) * 100.0, 1)

        app_doc = self.get_app(app_id) or {}
        classification = app_doc.get("classification", "UNCLASSIFIED")
        if environment == "test":
            data_status = "test"
        elif classification == "SAMPLE":
            data_status = "sample"
        elif classification == "REAL":
            data_status = "live"
        else:
            data_status = "unclassified"

        return {
            "app_id": app_id,
            "environment": environment,
            "start_date": start_dt.isoformat(),
            "end_date": end_dt.isoformat(),
            "data_status": data_status,
            "pageviews": {"value": float(cpv), "previous_value": float(ppv), "change_pct": _pct(cpv, ppv), "available": True},
            "visitors": {"value": float(cvis), "previous_value": float(pvis), "change_pct": _pct(cvis, pvis), "available": cvis_avail},
            "sessions": {"value": float(cses), "previous_value": float(pses), "change_pct": _pct(cses, pses), "available": cses_avail},
            "bounce_rate": {"value": float(cbr), "previous_value": float(pbr), "change_pct": _pct(cbr, pbr), "available": cses_avail},
            "avg_duration_sec": {"value": float(cdur), "previous_value": float(pdur), "change_pct": _pct(cdur, pdur), "available": cses_avail},
        }

    def get_timeseries_metrics(
        self,
        app_id: str,
        environment: str,
        interval: str,
        start_dt: datetime,
        end_dt: datetime,
        fill_sparse: bool = True,
    ) -> List[Dict[str, Any]]:
        events, _ = self._fetch_window_data(app_id, environment, start_dt, end_dt)

        buckets: Dict[str, Dict[str, Any]] = {}
        s_utc = start_dt if start_dt.tzinfo else start_dt.replace(tzinfo=timezone.utc)
        e_utc = end_dt if end_dt.tzinfo else end_dt.replace(tzinfo=timezone.utc)

        # Pre-populate contiguous intervals for complete timeline and sparse-data support
        if fill_sparse:
            if interval == "hour":
                curr = s_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
                bound = e_utc.astimezone(timezone.utc)
                while curr <= bound:
                    bucket_key = curr.strftime("%Y-%m-%dT%H:00:00+00:00")
                    buckets[bucket_key] = {"pageviews": 0, "sessions": set(), "visitors": set()}
                    curr += timedelta(hours=1)
            else:
                curr = s_utc.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                bound = e_utc.astimezone(timezone.utc)
                while curr <= bound:
                    bucket_key = curr.strftime("%Y-%m-%dT00:00:00+00:00")
                    buckets[bucket_key] = {"pageviews": 0, "sessions": set(), "visitors": set()}
                    curr += timedelta(days=1)

        for e in events:
            ts = _parse_iso(e.get("timestamp"))
            if interval == "hour":
                bucket_key = ts.strftime("%Y-%m-%dT%H:00:00+00:00")
            else:
                bucket_key = ts.strftime("%Y-%m-%dT00:00:00+00:00")

            if bucket_key not in buckets:
                buckets[bucket_key] = {"pageviews": 0, "sessions": set(), "visitors": set()}

            if str(e.get("event_type", "")).lower() == "pageview":
                buckets[bucket_key]["pageviews"] += 1
            if e.get("session_id"):
                buckets[bucket_key]["sessions"].add(e.get("session_id"))
            if e.get("visitor_id"):
                buckets[bucket_key]["visitors"].add(e.get("visitor_id"))

        result = []
        for key in sorted(buckets.keys()):
            result.append({
                "timestamp": key,
                "pageviews": buckets[key]["pageviews"],
                "sessions": len(buckets[key]["sessions"]),
                "visitors": len(buckets[key]["visitors"]),
            })
        return result

    def get_top_pages(
        self,
        app_id: str,
        environment: str,
        start_dt: datetime,
        end_dt: datetime,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        events, sessions = self._fetch_window_data(app_id, environment, start_dt, end_dt)

        pages: Dict[str, Dict[str, Any]] = {}
        for e in events:
            if str(e.get("event_type", "")).lower() != "pageview":
                continue
            path = e.get("page_path") or "/"
            if path not in pages:
                pages[path] = {"views": 0, "visitors": set(), "bounces": 0, "durations": []}
            pages[path]["views"] += 1
            if e.get("visitor_id"):
                pages[path]["visitors"].add(e.get("visitor_id"))

        for s in sessions:
            entry = s.get("entry_page") or "/"
            if entry in pages:
                if s.get("is_bounce") and (s.get("duration_seconds", 0) < 10):
                    pages[entry]["bounces"] += 1
                pages[entry]["durations"].append(s.get("duration_seconds", 0))

        items = []
        for path, data in pages.items():
            views = data["views"]
            vis_count = len(data["visitors"])
            total_dur = sum(data["durations"])
            dur_count = len(data["durations"])
            avg_dur = round(total_dur / dur_count, 1) if dur_count > 0 else 0.0
            bounce_rate = round((data["bounces"] / dur_count * 100.0), 1) if dur_count > 0 else 0.0

            items.append({
                "page_path": path,
                "views_count": views,
                "visitors_count": vis_count,
                "bounce_rate": bounce_rate,
                "avg_duration_sec": avg_dur,
            })

        items.sort(key=lambda x: x["views_count"], reverse=True)
        return items[:limit]

    def get_top_referrers(
        self,
        app_id: str,
        environment: str,
        start_dt: datetime,
        end_dt: datetime,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        events, _ = self._fetch_window_data(app_id, environment, start_dt, end_dt)

        app_doc = self.get_app(app_id) or {}
        allowed_origins = app_doc.get("allowed_origins")

        refs: Dict[str, Dict[str, Any]] = {}
        for e in events:
            domain = e.get("referrer_domain")
            cat = e.get("referrer_category") or classify_referrer(domain, allowed_origins)
            if not domain:
                domain = cat if (cat and cat != "Direct / None") else "Direct / None"
            if domain not in refs:
                refs[domain] = {"category": cat, "views": 0, "visitors": set()}
            refs[domain]["views"] += 1
            if e.get("visitor_id"):
                refs[domain]["visitors"].add(e.get("visitor_id"))

        items = []
        for domain, data in refs.items():
            items.append({
                "referrer_domain": domain,
                "referrer_category": data.get("category", "Direct / None"),
                "views_count": data["views"],
                "visitors_count": len(data["visitors"]),
            })
        items.sort(key=lambda x: x["views_count"], reverse=True)
        return items[:limit]

    def get_device_breakdown(
        self,
        app_id: str,
        environment: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> Dict[str, Any]:
        events, _ = self._fetch_window_data(app_id, environment, start_dt, end_dt)

        dev_counts: Dict[str, int] = {}
        os_counts: Dict[str, int] = {}
        br_counts: Dict[str, int] = {}
        total = len(events) or 1

        for e in events:
            dev = e.get("device_family") or "Unknown"
            os_name = e.get("os_family") or "Unknown"
            browser = e.get("browser_family") or "Unknown"

            dev_counts[dev] = dev_counts.get(dev, 0) + 1
            os_counts[os_name] = os_counts.get(os_name, 0) + 1
            br_counts[browser] = br_counts.get(browser, 0) + 1

        def _make_list(counts: Dict[str, int]):
            items = []
            for k, count in counts.items():
                items.append({
                    "name": k,
                    "count": count,
                    "percentage": round((count / total) * 100.0, 1),
                })
            items.sort(key=lambda x: x["count"], reverse=True)
            return items

        return {
            "devices": _make_list(dev_counts),
            "os": _make_list(os_counts),
            "browsers": _make_list(br_counts),
        }

    def get_geo_breakdown(
        self,
        app_id: str,
        environment: str,
        start_dt: datetime,
        end_dt: datetime,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        events, _ = self._fetch_window_data(app_id, environment, start_dt, end_dt)

        geo: Dict[str, Dict[str, Any]] = {}
        for e in events:
            cc, city = geography(e)
            cc = cc or "Unknown"
            key = f"{cc}:{city}"
            if key not in geo:
                geo[key] = {"country": cc, "city": city, "views": 0, "visitors": set()}
            geo[key]["views"] += 1
            if e.get("visitor_id"):
                geo[key]["visitors"].add(e.get("visitor_id"))

        items = []
        for key, data in geo.items():
            items.append({
                "country_code": data["country"],
                "city_name": data["city"],
                "visitors_count": len(data["visitors"]),
                "pageviews_count": data["views"],
            })
        items.sort(key=lambda x: x["pageviews_count"], reverse=True)
        return items[:limit]

    def get_live_events(
        self,
        app_id: str,
        environment: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        snaps = self.db.events_col(app_id, environment).order_by("timestamp", direction="DESCENDING").limit(limit).get()
        return [s.to_dict() for s in snaps]

    def get_events_for_export(
        self,
        app_id: str,
        environment: str,
        start_dt: datetime,
        end_dt: datetime,
        limit: int = 10000,
    ) -> List[Dict[str, Any]]:
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()
        snaps = self.db.events_col(app_id, environment).where("timestamp", ">=", start_iso).where("timestamp", "<=", end_iso).order_by("timestamp", direction="ASCENDING").limit(limit).get()
        return [s.to_dict() for s in snaps]

    # ==========================================================================
    # Audit Logs
    # ==========================================================================

    def log_audit(
        self,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: Dict[str, Any],
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        log_id = str(uuid.uuid4())
        data = {
            "id": log_id,
            "user_id": str(user_id),
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "details": details,
            "ip_address": ip_address,
            "timestamp": _iso_now(),
        }
        self.db.audit_logs_col.document(log_id).set(data)
        return data


# Repository Singleton
firestore_repo = FirestoreRepo()


def get_repo() -> FirestoreRepo:
    return firestore_repo
