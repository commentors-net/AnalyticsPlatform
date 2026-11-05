"""Google Cloud Firestore Database Layer for AnalyticsPlatform.

Provides dedicated collection namespace isolation ('analytics_*'),
atomic idempotency claims, tenant and environment isolation,
and support for both production GCP Firestore and in-memory mock testing.
"""

from __future__ import annotations

import logging
import copy
import threading
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from api.app.core.config import settings

logger = logging.getLogger("analytics_platform.firestore")

try:
    from google.cloud import firestore
    from google.api_core.exceptions import GoogleAPIError
    HAS_FIRESTORE_SDK = True
except ImportError:
    HAS_FIRESTORE_SDK = False


# ==============================================================================
# In-Memory Mock Firestore (for offline unit testing & fast deterministic tests)
# ==============================================================================

class MockDocumentSnapshot:
    def __init__(self, doc_id: str, data: Optional[Dict[str, Any]] = None, exists: bool = True, reference: Optional[Any] = None):
        self.id = doc_id
        self._data = dict(data) if data is not None else None
        self.exists = exists and (data is not None)
        self.reference = reference

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._data) if self._data else {}


class MockDocumentReference:
    def __init__(self, doc_id: str, store: Dict[str, Any], path: str):
        self.id = doc_id
        self._store = store
        self._path = path

    @property
    def path(self):
        return self._path

    def collections(self):
        prefix = self._path + "/"
        names = {key[len(prefix):].split('/')[0] for key in self._store if key.startswith(prefix)}
        return [MockCollectionReference(prefix + name, self._store) for name in sorted(names)]

    def get(self, transaction=None) -> MockDocumentSnapshot:
        if self._path in self._store:
            return MockDocumentSnapshot(self.id, self._store[self._path], exists=True, reference=self)
        return MockDocumentSnapshot(self.id, None, exists=False, reference=self)

    def set(self, data: Dict[str, Any], merge: bool = False) -> None:
        if merge and self._path in self._store:
            existing = dict(self._store[self._path])
            existing.update(data)
            self._store[self._path] = existing
        else:
            self._store[self._path] = dict(data)

    def create(self, data: Dict[str, Any]) -> None:
        from google.api_core.exceptions import AlreadyExists
        if self._path in self._store:
            raise AlreadyExists("Document already exists")
        self._store[self._path] = dict(data)

    def update(self, data: Dict[str, Any]) -> None:
        if self._path in self._store:
            self._store[self._path].update(data)
        else:
            self._store[self._path] = dict(data)

    def delete(self) -> None:
        self._store.pop(self._path, None)

    def collection(self, sub_name: str) -> MockCollectionReference:
        return MockCollectionReference(f"{self._path}/{sub_name}", self._store)


class MockQuery:
    def __init__(self, collection_path: str, store: Dict[str, Any], filters: Optional[List[Tuple[str, str, Any]]] = None, order_field: Optional[str] = None, order_dir: str = "ASCENDING", limit_val: Optional[int] = None):
        self._path = collection_path
        self._store = store
        self._filters = filters or []
        self._order_field = order_field
        self._order_dir = order_dir
        self._limit_val = limit_val

    def where(self, field_path: str, op_string: str, value: Any) -> MockQuery:
        new_filters = list(self._filters)
        new_filters.append((field_path, op_string, value))
        return MockQuery(self._path, self._store, new_filters, self._order_field, self._order_dir, self._limit_val)

    def order_by(self, field_path: str, direction: str = "ASCENDING") -> MockQuery:
        return MockQuery(self._path, self._store, self._filters, field_path, direction, self._limit_val)

    def limit(self, count: int) -> MockQuery:
        return MockQuery(self._path, self._store, self._filters, self._order_field, self._order_dir, count)

    def _get_matches(self) -> List[MockDocumentSnapshot]:
        prefix = f"{self._path}/"
        results = []
        for path, doc_data in self._store.items():
            if path.startswith(prefix):
                remainder = path[len(prefix):]
                if "/" not in remainder:
                    # Direct child document
                    doc_id = remainder
                    match = True
                    for field, op, val in self._filters:
                        doc_val = doc_data.get(field)
                        if op == "==" and doc_val != val:
                            match = False
                            break
                        elif op == ">=" and (doc_val is None or doc_val < val):
                            match = False
                            break
                        elif op == "<=" and (doc_val is None or doc_val > val):
                            match = False
                            break
                        elif op == ">" and (doc_val is None or doc_val <= val):
                            match = False
                            break
                        elif op == "<" and (doc_val is None or doc_val >= val):
                            match = False
                            break
                    if match:
                        ref = MockDocumentReference(doc_id, self._store, path)
                        results.append(MockDocumentSnapshot(doc_id, doc_data, exists=True, reference=ref))

        if self._order_field:
            reverse = self._order_dir in ("DESCENDING", "DESC")
            results.sort(key=lambda s: s.to_dict().get(self._order_field) or "", reverse=reverse)

        if self._limit_val is not None:
            results = results[:self._limit_val]

        return results

    def stream(self):
        for snap in self._get_matches():
            yield snap

    def get(self) -> List[MockDocumentSnapshot]:
        return self._get_matches()


class MockCollectionReference(MockQuery):
    def __init__(self, collection_path: str, store: Dict[str, Any]):
        super().__init__(collection_path, store)
        self.path = collection_path

    def document(self, document_id: Optional[str] = None) -> MockDocumentReference:
        doc_id = document_id or uuid.uuid4().hex
        return MockDocumentReference(doc_id, self._store, f"{self.path}/{doc_id}")

    def list_documents(self, page_size=None):
        prefix = self.path + "/"
        ids = {key[len(prefix):].split('/')[0] for key in self._store if key.startswith(prefix)}
        return [self.document(doc_id) for doc_id in sorted(ids)]

    def add(self, data: Dict[str, Any]) -> Tuple[Any, MockDocumentReference]:
        doc_id = uuid.uuid4().hex
        ref = self.document(doc_id)
        ref.set(data)
        return (None, ref)


class MockFirestoreClient:
    def __init__(self):
        self._store: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def collection(self, name: str) -> MockCollectionReference:
        return MockCollectionReference(name, self._store)

    def collections(self):
        root_cols = set()
        for path in self._store.keys():
            parts = path.split("/")
            if len(parts) >= 2:
                root_cols.add(parts[0])
        return [MockCollectionReference(col, self._store) for col in root_cols]

    def clear(self):
        self._store.clear()


# ==============================================================================
# Firestore Database Service (Unified Wrapper)
# ==============================================================================

class FirestoreDB:
    """Encapsulates Firestore access with strict collection namespace prefixing ('analytics_*')."""

    def __init__(self) -> None:
        self.project_id = settings.GCP_PROJECT_ID
        self.database_id = settings.FIRESTORE_DATABASE
        self.prefix = settings.FIRESTORE_COLLECTION_PREFIX  # "analytics_"
        self._client = None
        self._is_mock = False

    @property
    def client(self):
        if self._client is None:
            self._client = self._init_client()
        return self._client

    def _init_client(self):
        force_mock = getattr(settings, "USE_MOCK_FIRESTORE", False) or os.environ.get("USE_MOCK_FIRESTORE") == "1"
        if force_mock:
            logger.info("Initializing in-memory Mock Firestore client")
            self._is_mock = True
            return MockFirestoreClient()

        if not HAS_FIRESTORE_SDK:
            logger.warning("google-cloud-firestore not installed. Falling back to Mock Firestore.")
            self._is_mock = True
            return MockFirestoreClient()

        try:
            # First try default credentials (metadata server on Cloud Run or ADC)
            c = firestore.Client(project=self.project_id, database=self.database_id)
            logger.info(f"Initialized Google Cloud Firestore client for project '{self.project_id}'")
            return c
        except Exception as exc:
            # If running locally without credentials and environment is testing/development, fallback to mock
            if settings.ENVIRONMENT in ("testing", "development"):
                logger.warning(f"Could not initialize GCP Firestore client ({exc}). Falling back to in-memory mock for {settings.ENVIRONMENT}.")
                self._is_mock = True
                return MockFirestoreClient()
            raise

    # --------------------------------------------------------------------------
    # Collection Accessors (Guaranteed Dedicated Prefix)
    # --------------------------------------------------------------------------

    def run_transaction(self, callback):
        if isinstance(self.client, MockFirestoreClient):
            class Transaction:
                def set(self, ref, data): ref.set(data)
                def update(self, ref, data): ref.update(data)
                def create(self, ref, data): ref.create(data)
                def delete(self, ref): ref.delete()
            with self.client._lock:
                before = copy.deepcopy(self.client._store)
                try:
                    return callback(Transaction())
                except Exception:
                    self.client._store.clear()
                    self.client._store.update(before)
                    raise
        return firestore.transactional(callback)(self.client.transaction())

    @property
    def deletions_col(self):
        return self.client.collection(f"{self.prefix}deletions")

    @property
    def users_col(self):
        return self.client.collection(f"{self.prefix}users")

    @property
    def apps_col(self):
        return self.client.collection(f"{self.prefix}apps")

    @property
    def permissions_col(self):
        return self.client.collection(f"{self.prefix}user_permissions")

    @property
    def api_keys_col(self):
        return self.client.collection(f"{self.prefix}api_keys")

    @property
    def idempotency_col(self):
        return self.client.collection(f"{self.prefix}idempotency")

    @property
    def audit_logs_col(self):
        return self.client.collection(f"{self.prefix}audit_logs")

    def events_col(self, app_id: str, environment: str):
        """Subcollection: analytics_data/{app_id}_{environment}/events"""
        root_doc = f"{app_id}_{environment}"
        return self.client.collection(f"{self.prefix}data").document(root_doc).collection("events")

    def sessions_col(self, app_id: str, environment: str):
        """Subcollection: analytics_data/{app_id}_{environment}/sessions"""
        root_doc = f"{app_id}_{environment}"
        return self.client.collection(f"{self.prefix}data").document(root_doc).collection("sessions")

    # --------------------------------------------------------------------------
    # Health Probe
    # --------------------------------------------------------------------------

    def ping(self) -> bool:
        """Verify Firestore reachability."""
        try:
            # Read metadata doc or check collection
            ref = self.client.collection(f"{self.prefix}health").document("ping")
            ref.set({"ping_at": datetime.now(timezone.utc).isoformat()})
            return True
        except Exception as exc:
            logger.error(f"Firestore ping failed: {exc}")
            return False


# Singleton instance
firestore_db = FirestoreDB()


def get_firestore() -> FirestoreDB:
    """FastAPI dependency for accessing FirestoreDB."""
    return firestore_db

